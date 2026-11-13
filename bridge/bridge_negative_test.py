#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Negative tests for bridge_check.py. Self-contained: builds small fake sites in a temp directory.

A site that names other contracts must not match; a malformed fingerprint or an unreadable site must
never pass. Run from this folder: python3 bridge_negative_test.py
Network scenarios use a local HTTP server on 127.0.0.1 only.
"""
import copy
import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading

spec = importlib.util.spec_from_file_location("bridge", "bridge_check.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

REF = json.load(open("../references/testnet/reference_testnet_97cd13f3.contracts.json", encoding="utf-8"))
A = lambda ch, nm: REF["contracts"][ch][nm]["address"].lower()
CAW = [A("L1", n) for n in ("CawProfile", "CawProfileMinter", "CawProfileQuoter", "CawProfileMarketplace",
                            "CawNetworkManager", "CawProfileLens", "SmartEOA", "MintableCaw")] + \
      [A("L2", "CawProfileLedger"), A("L2", "CawActions")]
EXTERNAL = ["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            "0xdac17f958d2ee523a2206206994597c13d831ec7"]
OFFICIAL = CAW + EXTERNAL
UNOFFICIAL = ["0x1111111111111111111111111111111111111111", "0x2222222222222222222222222222222222222222"]
ENTRY, VENDOR = "assets/index-AAAA1111.js", "assets/vendor-BBBB2222.js"
INDEX = ('<!doctype html><html><head><script type="module" crossorigin src="/%s"></script>'
         '<link rel="modulepreload" crossorigin href="/%s"></head><body><div id="root"></div></body></html>' % (ENTRY, VENDOR))
failures = []


def build(root, entry_addrs=OFFICIAL, entry_extra="", vendor_extra="", index=INDEX, write_entry=True):
    os.makedirs(os.path.join(root, "assets"), exist_ok=True)
    if index is not None:
        open(os.path.join(root, "index.html"), "w").write(index)
    if write_entry:
        consts = ",".join(f'k{i}="{a}"' for i, a in enumerate(entry_addrs))
        open(os.path.join(root, ENTRY), "w").write(f'import"./vendor-BBBB2222.js";const {consts};{entry_extra}function f(){{return 1}}')
    noise = '["0x0000000000000000000000000000000000000000","0xd6e6dbf4f7ea0ac412fd8b65ed297e64bb7a06e1"]'
    open(os.path.join(root, VENDOR), "w").write(f"const v={noise};{vendor_extra}")


def run(fp, root, source=None, reference=REF):
    try:
        r = B.check(source or B.DirSource(root), fp, reference)
        return r["verdict"], B.render(r)
    except B.Invalid as e:
        return "INVALID", str(e)
    except B.Unreadable as e:
        return "UNREADABLE", str(e)


def scenario(name, want, needles=(), build_kw=None, fp_mutate=None, builder=None, limits=None):
    tmp = tempfile.mkdtemp(prefix="bridge-test-")
    saved = (B.MAX_INDEX, B.MAX_SCRIPT)
    try:
        base = os.path.join(tmp, "control")
        build(base)
        fp = B.make_fingerprint(B.DirSource(base), "control")
        site = os.path.join(tmp, "site")
        if builder:
            builder(site)
        else:
            build(site, **(build_kw or {}))
        if fp_mutate:
            fp = fp_mutate(copy.deepcopy(fp))
        if limits:
            B.MAX_INDEX, B.MAX_SCRIPT = limits
        verdict, text = run(fp, site)
    finally:
        B.MAX_INDEX, B.MAX_SCRIPT = saved
        shutil.rmtree(tmp, ignore_errors=True)
    problems = []
    if verdict != want:
        problems.append(f"verdict {verdict}, expected {want}")
    for n in needles:
        if n not in text:
            problems.append(f"missing text '{n}'")
    print(f"[{'PASS' if not problems else 'FAIL'}] {name}: {verdict}")
    for p in problems:
        print(f"         !! {p}\n         {text[:300]}")
        failures.append(f"{name}: {p}")


# ---- the real thing, and the near misses
scenario("00 control: the site names exactly the fingerprint's addresses", "MATCH")
scenario("01 one official address replaced by an unofficial one", "DIFFERENT", ["MISSING", "UNEXPECTED", UNOFFICIAL[0]],
         build_kw={"entry_addrs": OFFICIAL[1:] + [UNOFFICIAL[0]]})
scenario("02 a copy pointed at its own contracts (all CAW addresses replaced)", "DIFFERENT", ["3 of 13"],
         build_kw={"entry_addrs": EXTERNAL + [f"0x{i:040x}".replace("0x000", "0xabc") for i in range(1, 11)]})
scenario("03 an extra unknown address in the entry script", "DIFFERENT", ["UNEXPECTED", UNOFFICIAL[1]],
         build_kw={"entry_extra": f'const x="{UNOFFICIAL[1]}";'})
scenario("04 same addresses written in upper or mixed case", "MATCH",
         build_kw={"entry_addrs": [a[:2] + a[2:].upper() if i % 2 else a for i, a in enumerate(OFFICIAL)]})
scenario("05 unknown addresses only in a library chunk (noise) do not matter", "MATCH",
         build_kw={"vendor_extra": f'const n="{UNOFFICIAL[0]}";'})
scenario("06 an official address split into pieces (not found as a whole)", "DIFFERENT", ["MISSING"],
         build_kw={"entry_addrs": OFFICIAL[1:], "entry_extra": f'const s="{OFFICIAL[0][:20]}"+"{OFFICIAL[0][20:]}";'})
scenario("07 KNOWN LIMIT: official addresses as decoys, another one built at run time", "MATCH",
         build_kw={"entry_extra": f'const u="{UNOFFICIAL[0][:12]}"+"{UNOFFICIAL[0][12:]}";'})

# ---- the fingerprint is broken
scenario("10 empty address list", "INVALID", ["empty"], fp_mutate=lambda f: f.__setitem__("addresses", []) or f)
scenario("11 malformed address", "INVALID", ["20-byte"], fp_mutate=lambda f: f["addresses"].__setitem__(0, "0x1234") or f)
scenario("12 generic address in the fingerprint", "INVALID", ["generic"],
         fp_mutate=lambda f: f["addresses"].append("0x" + "0" * 40) or f)
scenario("13 wrong kind", "INVALID", ["kind"], fp_mutate=lambda f: f.__setitem__("kind", "other") or f)
scenario("14 unknown schema version", "INVALID", ["schemaVersion"], fp_mutate=lambda f: f.__setitem__("schemaVersion", 2) or f)
scenario("15 duplicate addresses", "INVALID", ["duplicates"], fp_mutate=lambda f: f["addresses"].append(f["addresses"][0]) or f)

# ---- the site cannot be read: never a pass
scenario("20 no index.html", "UNREADABLE", ["index.html"], build_kw={"index": None})
scenario("21 index.html names no module script", "UNREADABLE", ["entry script"], build_kw={"index": "<html><body>hi</body></html>"})
scenario("22 the entry script is missing", "UNREADABLE", ["cannot read"], build_kw={"write_entry": False})
scenario("23 an entry path that points outside the site", "UNREADABLE", ["outside"],
         build_kw={"index": '<script type="module" src="/../../../etc/hostname"></script>'})
scenario("24 only an external script", "UNREADABLE", ["entry script"],
         build_kw={"index": '<script type="module" src="https://cdn.example.com/app.js"></script>'})
scenario("25 entry script larger than the limit", "UNREADABLE", ["larger"], limits=(2 * 1024 * 1024, 100))


# ---- network (local server only)
class H(http.server.BaseHTTPRequestHandler):
    mode, root = "normal", ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = os.path.join(self.root, self.path.lstrip("/").split("?")[0])
        if self.mode == "redirect" and self.path.endswith(".js"):
            self.send_response(302); self.send_header("location", "/elsewhere.js"); self.end_headers(); return
        if self.mode == "error500" and self.path.endswith(".js"):
            self.send_response(500); self.end_headers(); return
        if self.mode == "huge" and self.path.endswith(".js"):
            self.send_response(200); self.send_header("content-length", "999999999"); self.end_headers(); return
        try:
            data = open(p, "rb").read()
        except OSError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


def net(name, mode, want, needles=(), site_url=None):
    tmp = tempfile.mkdtemp(prefix="bridge-net-")
    try:
        build(os.path.join(tmp, "site"))
        fp = B.make_fingerprint(B.DirSource(os.path.join(tmp, "site")), "control")
        H.mode, H.root = mode, os.path.join(tmp, "site")
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = site_url or f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                src = B.HttpSource(url)
                verdict, text = run(fp, None, source=src)
            except B.Invalid as e:
                verdict, text = "INVALID", str(e)
        finally:
            srv.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    problems = [] if verdict == want else [f"verdict {verdict}, expected {want}"]
    problems += [f"missing text '{n}'" for n in needles if n not in text]
    print(f"[{'PASS' if not problems else 'FAIL'}] {name}: {verdict}")
    for p in problems:
        print(f"         !! {p}\n         {text[:300]}")
        failures.append(f"{name}: {p}")


net("30 served over HTTP (localhost)", "normal", "MATCH")
net("31 the entry script redirects", "redirect", "UNREADABLE", ["redirected"])
net("32 the server answers 500 for the script", "error500", "UNREADABLE", ["HTTP 500"])
net("33 the script declares an absurd size", "huge", "UNREADABLE", ["declares more than"])
net("34 plain http to another host", "normal", "INVALID", ["https"], site_url="http://example.com")
net("35 credentials in the address", "normal", "INVALID", ["credentials"], site_url="https://user:pw@example.com")

print()
if failures:
    print(f"{len(failures)} expectation(s) failed:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("all scenarios behaved as expected")
