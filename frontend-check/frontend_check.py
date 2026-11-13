#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Are the files a site serves the files a frontend manifest lists?

  frontend_check.py check (--site URL | --dir DIR) --manifest FILE_OR_HTTPS_URL [options]

For every path in the manifest the file is read from the site (or a directory), hashed with SHA-256
and compared with the manifest. Files that are not listed are not checked.

Result and exit code: MATCH 0, DIFFERENT 1, INVALID 2 (bad manifest or arguments), INCOMPLETE 3
(nothing differs, but some files could not be read: no conclusion, never a pass).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MAX_MANIFEST = 8 * 1024 * 1024
MAX_FILES = 5000
MAX_PATH = 300
HASH_RE = re.compile(r"^sha256-([0-9a-fA-F]{64})$")
# defaults; every one can be changed on the command line
LIMITS = {"file": 32 * 1024 * 1024, "total": 512 * 1024 * 1024, "timeout": 20.0, "deadline": 900.0, "concurrency": 4}
CHUNK = 64 * 1024


class Invalid(Exception):
    pass


class Problem(Exception):
    """A file could not be read. kind is 'missing' (HTTP 404) or 'error'."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------ manifest
def valid_path(p):
    if not isinstance(p, str) or not p or len(p) > MAX_PATH:
        return False
    if "\\" in p or "://" in p or p.startswith("/") or any(ord(c) < 32 for c in p):
        return False
    segs = p.split("/")
    return all(s not in ("", ".", "..") for s in segs)


def validate_manifest(m):
    problems = []
    if not isinstance(m, dict):
        return ["manifest is not an object"], {}
    if m.get("version") != 1:
        problems.append(f"unsupported version {m.get('version')!r} (this checker reads 1)")
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        problems.append("files missing or empty (a manifest that lists no files is refused, never passed)")
        return problems, {}
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files (more than {MAX_FILES})")
    clean = {}
    for p, h in files.items():
        if not valid_path(p):
            problems.append(f"bad path {p!r} (relative, no '..', no scheme, no backslash)")
            continue
        mm = HASH_RE.match(h) if isinstance(h, str) else None
        if not mm:
            problems.append(f"{p}: hash must be 'sha256-' and 64 hex digits")
            continue
        clean[p] = mm.group(1).lower()
    return problems, clean


# ------------------------------------------------------------------ budget and sources
class Budget:
    def __init__(self, total):
        self.left, self.lock = total, threading.Lock()

    def take(self, n):
        with self.lock:
            if n > self.left:
                return False
            self.left -= n
            return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def hash_stream(read, limit, budget):
    """read() returns the next chunk or b''. Hash it, stopping at the file limit or the budget."""
    h, n = hashlib.sha256(), 0
    while True:
        chunk = read(CHUNK)
        if not chunk:
            return h.hexdigest(), n
        n += len(chunk)
        if n > limit:
            raise Problem("error", f"larger than {limit} bytes")
        if not budget.take(len(chunk)):
            raise Problem("error", "total byte budget exceeded")
        h.update(chunk)


class DirSource:
    def __init__(self, root):
        self.root, self.name = os.path.realpath(root), f"directory {root}"

    def digest(self, path, limit, budget, timeout):
        p = os.path.realpath(os.path.join(self.root, path or "index.html"))
        if not p.startswith(self.root + os.sep):
            raise Problem("error", "path points outside the directory")
        try:
            with open(p, "rb") as f:
                return hash_stream(f.read, limit, budget)
        except FileNotFoundError:
            raise Problem("missing", "not found")
        except OSError:
            raise Problem("error", "cannot read")


class HttpSource:
    def __init__(self, url):
        u = urllib.parse.urlsplit(url.strip())
        local = u.hostname in ("localhost", "127.0.0.1", "::1")
        if u.scheme != "https" and not (u.scheme == "http" and local):
            raise Invalid("only https:// sites can be read (http:// is allowed for localhost only)")
        if not u.hostname or u.username or u.password:
            raise Invalid("a site address has a host name and no credentials")
        host = u.hostname if ":" not in u.hostname else f"[{u.hostname}]"
        self.base = f"{u.scheme}://{host}" + (f":{u.port}" if u.port else "")
        self.name = self.base
        self._opener = urllib.request.build_opener(_NoRedirect)

    def digest(self, path, limit, budget, timeout):
        target = "" if path == "" else urllib.parse.quote(path, safe="/")
        req = urllib.request.Request(f"{self.base}/{target}", headers={"user-agent": "caw-frontend-verify-files/0"})
        try:
            with self._opener.open(req, timeout=timeout) as r:
                declared = r.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise Problem("error", f"declares more than {limit} bytes")
                return hash_stream(r.read, limit, budget)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise Problem("error", "redirected (enter the address the site answers at)")
            raise Problem("missing" if e.code == 404 else "error", f"HTTP {e.code}")
        except Problem:
            raise
        except TimeoutError:
            raise Problem("error", "timed out")
        except Exception as e:
            raise Problem("error", type(e).__name__)


def load_manifest(spec):
    """A manifest from a local file or an https URL (read as it is; no redirects)."""
    if re.match(r"^https?://", spec):
        u = urllib.parse.urlsplit(spec)
        local = u.hostname in ("localhost", "127.0.0.1", "::1")
        if (u.scheme != "https" and not (u.scheme == "http" and local)) or u.username or u.password:
            raise Invalid("a manifest URL is https (http for localhost only) without credentials")
        try:
            req = urllib.request.Request(spec, headers={"user-agent": "caw-frontend-verify-files/0"})
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=LIMITS["timeout"]) as r:
                data = r.read(MAX_MANIFEST + 1)
        except Exception as e:
            raise Invalid(f"cannot read the manifest: {type(e).__name__}")
    else:
        try:
            with open(spec, "rb") as f:
                data = f.read(MAX_MANIFEST + 1)
        except OSError:
            raise Invalid("cannot read the manifest file")
    if len(data) > MAX_MANIFEST:
        raise Invalid(f"manifest is larger than {MAX_MANIFEST} bytes")
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        raise Invalid("manifest is not valid JSON")


# ------------------------------------------------------------------ the check
def check(source, manifest, index_from_root=False, limits=None):
    lim = dict(LIMITS, **(limits or {}))
    problems, files = validate_manifest(manifest)
    if problems:
        raise Invalid("; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
    budget, start = Budget(lim["total"]), time.monotonic()
    results = {}

    def one(path):
        if time.monotonic() - start > lim["deadline"]:
            return path, {"status": "error", "reason": "overall deadline exceeded"}
        fetch = "" if (index_from_root and path == "index.html") else path
        try:
            digest, size = source.digest(fetch, lim["file"], budget, lim["timeout"])
        except Problem as p:
            return path, {"status": p.kind, "reason": str(p)}
        if digest == files[path]:
            return path, {"status": "match"}
        return path, {"status": "mismatch", "expected": files[path], "actual": digest}

    with ThreadPoolExecutor(max_workers=max(1, min(8, lim["concurrency"]))) as ex:
        for path, res in ex.map(one, sorted(files)):
            results[path] = res
    count = lambda s: sum(1 for r in results.values() if r["status"] == s)
    mism, miss, err, ok = count("mismatch"), count("missing"), count("error"), count("match")
    verdict = "DIFFERENT" if (mism or miss) else ("INCOMPLETE" if err else "MATCH")
    return {"verdict": verdict, "site": source.name, "listed": len(files), "match": ok, "mismatch": mism,
            "missing": miss, "error": err, "results": results, "clientVersion": manifest.get("clientVersion")}


def render(r, show=20):
    lines = [f"site:     {r['site']}", f"manifest: {r['clientVersion'] or '(no version)'}",
             f"files:    {r['listed']} listed: {r['match']} match, {r['mismatch']} mismatch, {r['missing']} missing, {r['error']} unreadable"]
    bad = [(p, x) for p, x in sorted(r["results"].items()) if x["status"] != "match"]
    for p, x in bad[:show]:
        if x["status"] == "mismatch":
            lines.append(f"  MISMATCH    {p}  expected {x['expected'][:12]}…  got {x['actual'][:12]}…")
        elif x["status"] == "missing":
            lines.append(f"  MISSING     {p}")
        else:
            lines.append(f"  UNREADABLE  {p}  ({x['reason']})")
    if len(bad) > show:
        lines.append(f"  … and {len(bad) - show} more")
    lines.append(f"VERDICT: {r['verdict']}")
    lines.append("note: only the files the manifest lists were checked; files it does not list are not covered.")
    if r["verdict"] == "INCOMPLETE":
        lines.append("note: nothing differs, but some files could not be read, so there is no conclusion.")
    return "\n".join(lines)


CODES = {"MATCH": 0, "DIFFERENT": 1, "INVALID": 2, "INCOMPLETE": 3}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("check")
    sp.add_argument("--site")
    sp.add_argument("--dir")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--index-from-root", action="store_true", help="read index.html from '/' (hosts that redirect /index.html to /)")
    sp.add_argument("--concurrency", type=int, default=LIMITS["concurrency"])
    sp.add_argument("--max-file-mb", type=float, default=LIMITS["file"] / 2**20)
    sp.add_argument("--max-total-mb", type=float, default=LIMITS["total"] / 2**20)
    sp.add_argument("--timeout", type=float, default=LIMITS["timeout"])
    sp.add_argument("--deadline", type=float, default=LIMITS["deadline"])
    sp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if (a.site is None) == (a.dir is None):
            raise Invalid("give either --site or --dir")
        src = HttpSource(a.site) if a.site else DirSource(a.dir)
        limits = {"file": int(a.max_file_mb * 2**20), "total": int(a.max_total_mb * 2**20), "timeout": a.timeout,
                  "deadline": a.deadline, "concurrency": a.concurrency}
        r = check(src, load_manifest(a.manifest), a.index_from_root, limits)
    except Invalid as e:
        print(json.dumps({"tool": "frontend-check", "verdict": "INVALID", "reason": str(e)}) if a.json else f"VERDICT: INVALID: {e}")
        return CODES["INVALID"]
    if a.json:
        slim = {k: v for k, v in r.items() if k != "results"}
        slim["tool"] = "frontend-check"
        slim["flagged"] = [dict(path=p, **x) for p, x in sorted(r["results"].items()) if x["status"] != "match"][:50]
        print(json.dumps(slim))
    else:
        print(render(r))
    return CODES[r["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
