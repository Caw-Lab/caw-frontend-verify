#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Check several sites and write one status file for the web page (or for a scheduled monitor).

  make_status.py --sites sites.txt --releases releases.json --out status.json [--skip-chain]

sites.txt: one https address per line; empty lines and lines starting with # are ignored.
Each site is checked with verify_site.py (run as a separate program, JSON result read). A site whose
check cannot be run or read is recorded as such, never as a match.

status.json (v1): {"schemaVersion": 1, "kind": "caw-verify-status", "generatedAt": "<UTC time>",
                   "sites": [{"site": "<address>", "result": <verify_site.py --json output>}, ...]}
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_SITES = 100


class Invalid(Exception):
    pass


def read_sites(path):
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        raise Invalid("cannot read the sites file")
    sites = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if not re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?/?$", ln) and not re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?/?$", ln):
            raise Invalid(f"not a site address (https://host, or http://localhost): {ln[:60]}")
        sites.append(ln.rstrip("/"))
    if not sites:
        raise Invalid("the sites file lists no sites (a status of nothing is refused)")
    if len(set(sites)) != len(sites):
        raise Invalid("the sites file repeats a site")
    if len(sites) > MAX_SITES:
        raise Invalid(f"more than {MAX_SITES} sites")
    return sites


def check_site(site, releases, skip_chain):
    cmd = [sys.executable, "-I", os.path.join(HERE, "verify_site.py"), "--site", site, "--releases", releases, "--json"]
    if skip_chain:
        cmd.append("--skip-chain")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    except subprocess.TimeoutExpired:
        return {"site": site, "error": "the check timed out"}
    try:
        res = json.loads(p.stdout)
    except ValueError:
        return {"site": site, "error": f"no JSON result (exit {p.returncode})"}
    if p.returncode == 2 or "releases" not in res:
        return {"site": site, "error": res.get("reason", "the registry or the arguments were refused")}
    return {"site": site, "result": res}


def build(sites, releases, skip_chain):
    return {"schemaVersion": 1, "kind": "caw-verify-status",
            "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sites": [check_site(s, releases, skip_chain) for s in sites]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sites", required=True)
    ap.add_argument("--releases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-chain", action="store_true")
    a = ap.parse_args(argv)
    try:
        sites = read_sites(a.sites)
    except Invalid as e:
        print(f"INVALID: {e}")
        return 2
    status = build(sites, a.releases, a.skip_chain)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1)
        f.write("\n")
    bad = [s["site"] for s in status["sites"] if "error" in s]
    print(f"wrote {a.out}: {len(status['sites'])} site(s)" + (f"; could not be checked: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
