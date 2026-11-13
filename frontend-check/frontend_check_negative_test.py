#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Negative tests for frontend_check.py. Self-contained: fake sites in a temp directory, a local HTTP
server on 127.0.0.1 only. A changed, missing or unreadable file must never end in MATCH, and a manifest
that lists nothing (or something unsafe) must be refused.

Run from this folder: python3 frontend_check_negative_test.py
"""
import copy
import hashlib
import http.server
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time

spec = importlib.util.spec_from_file_location("fc", "frontend_check.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

FILES = {
    "index.html": b"<!doctype html><title>app</title><script type=module src=/assets/app-1.js></script>",
    "assets/app-1.js": b"console.log('app');" * 50,
    "assets/style-2.css": b"body{margin:0}",
    "img/logo.png": bytes(range(256)) * 20,
    "favicon.ico": b"\x00\x00\x01\x00",
}
failures = []


def sha(b):
    return "sha256-" + hashlib.sha256(b).hexdigest()


def manifest(files=FILES):
    return {"version": 1, "clientVersion": "test-1", "builtAt": "2026-01-01T00:00:00Z", "files": {p: sha(b) for p, b in files.items()}}


def write_site(root, files):
    for p, b in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, p)) or root, exist_ok=True)
        open(os.path.join(root, p), "wb").write(b)


def verdict_of(source, man, **kw):
    try:
        r = F.check(source, man, **kw)
        return r["verdict"], F.render(r), r
    except F.Invalid as e:
        return "INVALID", str(e), None


def report(name, want, got, text, needles):
    problems = [] if got == want else [f"verdict {got}, expected {want}"]
    problems += [f"missing text '{n}'" for n in needles if n not in text]
    print(f"[{'PASS' if not problems else 'FAIL'}] {name}: {got}")
    for p in problems:
        print(f"         !! {p}\n         {text[:400]}")
        failures.append(f"{name}: {p}")


def dir_scenario(name, want, needles=(), site_files=None, mutate=None, limits=None, saved=None):
    tmp = tempfile.mkdtemp(prefix="fc-test-")
    try:
        write_site(tmp, FILES if site_files is None else site_files)
        man = manifest()
        if mutate:
            man = mutate(copy.deepcopy(man))
        got, text, _ = verdict_of(F.DirSource(tmp), man, limits=limits)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    report(name, want, got, text, needles)


def changed(files, path, data):
    d = dict(files)
    d[path] = data
    return d


# ---- the files
dir_scenario("00 control: every file as listed", "MATCH")
dir_scenario("01 one file changed by one byte", "DIFFERENT", ["MISMATCH", "assets/app-1.js"],
             site_files=changed(FILES, "assets/app-1.js", FILES["assets/app-1.js"] + b" "))
dir_scenario("02 a listed file is missing", "DIFFERENT", ["MISSING", "favicon.ico"],
             site_files={p: b for p, b in FILES.items() if p != "favicon.ico"})
dir_scenario("03 every file missing", "DIFFERENT", ["5 missing"], site_files={})
dir_scenario("04 an extra file the manifest does not list (not covered, and the report says so)", "MATCH", ["not covered"],
             site_files=dict(FILES, **{"assets/extra.js": b"evil()"}))
dir_scenario("05 a changed file and an unreadable one: DIFFERENT wins", "DIFFERENT", ["MISMATCH"],
             site_files=changed(FILES, "index.html", b"x"), limits={"file": 40})
dir_scenario("06 hash written in upper case", "MATCH",
             mutate=lambda m: m["files"].__setitem__("index.html", "sha256-" + m["files"]["index.html"][7:].upper()) or m)

# ---- the manifest is broken: refused, never passed
dir_scenario("10 files is an empty object", "INVALID", ["lists no files"], mutate=lambda m: m.__setitem__("files", {}) or m)
dir_scenario("11 files is an empty array", "INVALID", ["lists no files"], mutate=lambda m: m.__setitem__("files", []) or m)
dir_scenario("12 files is a non-empty array", "INVALID", ["files missing"], mutate=lambda m: m.__setitem__("files", ["a"]) or m)
dir_scenario("13 unsupported version", "INVALID", ["version"], mutate=lambda m: m.__setitem__("version", 2) or m)
dir_scenario("14 a path with '..'", "INVALID", ["bad path"], mutate=lambda m: m["files"].__setitem__("../etc/passwd", sha(b"x")) or m)
dir_scenario("15 an absolute path", "INVALID", ["bad path"], mutate=lambda m: m["files"].__setitem__("/etc/passwd", sha(b"x")) or m)
dir_scenario("16 a URL as a path", "INVALID", ["bad path"], mutate=lambda m: m["files"].__setitem__("https://evil/x.js", sha(b"x")) or m)
dir_scenario("17 a backslash in a path", "INVALID", ["bad path"], mutate=lambda m: m["files"].__setitem__("a\\b.js", sha(b"x")) or m)
dir_scenario("18 malformed hash", "INVALID", ["hash must be"], mutate=lambda m: m["files"].__setitem__("index.html", "sha256-1234") or m)
dir_scenario("19 hash with the wrong prefix", "INVALID", ["hash must be"],
             mutate=lambda m: m["files"].__setitem__("index.html", "md5-" + "0" * 64) or m)
dir_scenario("20 manifest is not an object", "INVALID", ["not an object"], mutate=lambda m: ["x"])

saved_max = F.MAX_FILES
F.MAX_FILES = 3
dir_scenario("21 more files than the limit", "INVALID", ["more than 3"])
F.MAX_FILES = saved_max

# ---- resource limits on a directory
dir_scenario("30 a file larger than the per-file limit", "INCOMPLETE", ["larger than"], limits={"file": 100})
dir_scenario("31 total byte budget exhausted", "INCOMPLETE", ["budget"], limits={"total": 1500, "concurrency": 1})
dir_scenario("32 overall deadline exceeded", "INCOMPLETE", ["deadline"], limits={"deadline": -1})


# ---- over HTTP (127.0.0.1 only)
class H(http.server.BaseHTTPRequestHandler):
    mode, root, special = "normal", "", ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        rel = path.lstrip("/")
        if self.mode == "redirect_all" or (self.mode == "redirect_one" and rel == self.special):
            self.send_response(302); self.send_header("location", "/elsewhere"); self.end_headers(); return
        if self.mode == "index_redirect" and rel == "index.html":
            self.send_response(301); self.send_header("location", "/"); self.end_headers(); return
        if self.mode == "error500" and rel == self.special:
            self.send_response(500); self.end_headers(); return
        if self.mode == "huge_declared" and rel == self.special:
            self.send_response(200); self.send_header("content-length", "999999999"); self.end_headers(); return
        if self.mode == "huge_streamed" and rel == self.special:
            self.send_response(200); self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x" * 65536)
            except OSError:
                pass
            return
        if self.mode == "slow" and rel == self.special:
            time.sleep(2.5); self.send_response(200); self.end_headers(); return
        if rel == "":
            rel = "index.html"
        try:
            data = open(os.path.join(self.root, rel), "rb").read()
        except OSError:
            if self.mode == "spa":  # a single-page app: every unknown path answers 200 with the app
                data = FILES["index.html"]
                self.send_response(200); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data); return
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


def net(name, want, mode, special="", needles=(), site_files=None, limits=None, url=None, **kw):
    tmp = tempfile.mkdtemp(prefix="fc-net-")
    try:
        write_site(tmp, FILES if site_files is None else site_files)
        H.mode, H.root, H.special = mode, tmp, special
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            try:
                src = F.HttpSource(url or f"http://127.0.0.1:{srv.server_address[1]}")
                got, text, _ = verdict_of(src, manifest(), limits=limits, **kw)
            except F.Invalid as e:
                got, text = "INVALID", str(e)
        finally:
            srv.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    report(name, want, got, text, needles)


net("40 served over HTTP", "MATCH", "normal")
net("41 one file redirects", "INCOMPLETE", "redirect_one", "assets/app-1.js", ["redirected"])
net("42 every file redirects", "INCOMPLETE", "redirect_all", "", ["5 unreadable"])
net("43 index.html redirects to / (a static host)", "INCOMPLETE", "index_redirect", "", ["redirected"])
net("44 ...and --index-from-root reads it from /", "MATCH", "index_redirect", "", index_from_root=True)
net("45 one file answers 500", "INCOMPLETE", "error500", "assets/style-2.css", ["HTTP 500"])
net("46 a file declares an absurd size", "INCOMPLETE", "huge_declared", "img/logo.png", ["declares more than"])
net("47 a file streams more than the limit without declaring a size", "INCOMPLETE", "huge_streamed", "img/logo.png",
    ["larger than"], limits={"file": 1_000_000})
net("48 a file never answers (timeout)", "INCOMPLETE", "slow", "favicon.ico", ["timed out"], limits={"timeout": 1.0})
net("49 a site that serves the app for every unknown path (the missing file is a mismatch, not a pass)", "DIFFERENT", "spa",
    site_files={p: b for p, b in FILES.items() if p != "assets/style-2.css"}, needles=["MISMATCH"])
net("50 plain http to another host", "INVALID", "normal", url="http://example.com", needles=["https"])
net("51 credentials in the address", "INVALID", "normal", url="https://user:pw@example.com", needles=["credentials"])
net("52 server answers nothing (no listener)", "INCOMPLETE", "normal", url="http://127.0.0.1:9")

print()
if failures:
    print(f"{len(failures)} expectation(s) failed:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("all scenarios behaved as expected")
