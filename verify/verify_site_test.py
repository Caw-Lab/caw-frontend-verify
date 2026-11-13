#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Tests for verify_site.py. Self-contained: a fake site and fake registries in a temp directory; the
chain check is skipped (--skip-chain). The three tools are run for real, as separate programs.

Run from this folder: python3 verify_site_test.py
"""
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REAL_REF = os.path.join(ROOT, "references", "testnet", "reference_testnet_97cd13f3.contracts.json")
REF = json.load(open(REAL_REF, encoding="utf-8"))
A = lambda ch, nm: REF["contracts"][ch][nm]["address"].lower()
ADDRS = [A("L1", n) for n in ("CawProfile", "CawProfileMinter", "CawNetworkManager", "CawProfileQuoter")] + [A("L2", "CawActions")]
OTHER = ["0x1111111111111111111111111111111111111111", "0x2222222222222222222222222222222222222222",
         "0x3333333333333333333333333333333333333333", "0x4444444444444444444444444444444444444444",
         "0x5555555555555555555555555555555555555555"]
ENTRY = "assets/index-AAAA1111.js"
INDEX = f'<!doctype html><script type="module" src="/{ENTRY}"></script>'
failures = []


def site_files(addrs):
    consts = ",".join(f'k{i}="{a}"' for i, a in enumerate(addrs))
    return {"index.html": INDEX.encode(), ENTRY: f"const {consts};function f(){{return 1}}".encode(), "assets/style-2.css": b"body{margin:0}"}


def write_site(root, files):
    for p, b in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, p)) or root, exist_ok=True)
        open(os.path.join(root, p), "wb").write(b)


def fingerprint(addrs, name):
    return {"schemaVersion": 1, "kind": "caw-frontend-address-fingerprint", "name": name, "createdAt": "2026-01-01",
            "derivedFrom": {"description": "test", "entryFile": ENTRY}, "addresses": sorted(addrs)}


def manifest(files):
    return {"version": 1, "clientVersion": "test-1", "builtAt": "2026-01-01T00:00:00Z",
            "files": {p: "sha256-" + hashlib.sha256(b).hexdigest() for p, b in files.items()}}


def release(rid, kind="upstream", manifest_file=None, fp="fp-a.json"):
    return {"id": rid, "publisher": {"name": f"publisher of {rid}", "kind": kind}, "network": "testnet",
            "source": {"repo": "Example/Repo", "commit": "a" * 40, "tagged": False},
            "lineage": {"basedOn": None, "note": f"test release {rid}"},
            "frontend": {"addressFingerprint": fp, "manifest": manifest_file}, "contracts": {"reference": "ref.json"}}


def registry(releases):
    return {"schemaVersion": 1, "kind": "caw-releases", "releases": releases}


def run(tmp, reg, site_dir, extra=()):
    reg_path = os.path.join(tmp, "releases.json")
    json.dump(reg, open(reg_path, "w"))
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "verify_site.py"), "--dir", site_dir, "--releases", reg_path,
                        "--skip-chain", *extra], capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout


def scenario(name, want_code, needles=(), absent=(), build=None, extra=()):
    tmp = tempfile.mkdtemp(prefix="verify-test-")
    try:
        site = os.path.join(tmp, "site")
        write_site(site, site_files(ADDRS))
        shutil.copy(REAL_REF, os.path.join(tmp, "ref.json"))
        json.dump(fingerprint(ADDRS, "A"), open(os.path.join(tmp, "fp-a.json"), "w"))
        json.dump(fingerprint(OTHER, "other"), open(os.path.join(tmp, "fp-other.json"), "w"))
        json.dump(manifest(site_files(ADDRS)), open(os.path.join(tmp, "manifest-a.json"), "w"))
        reg = registry([release("rel-a")])
        if build:
            reg = build(tmp, site, reg) or reg
        code, out = run(tmp, reg, site, extra)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    problems = [] if code == want_code else [f"exit {code}, expected {want_code}"]
    problems += [f"missing text '{n}'" for n in needles if n not in out]
    problems += [f"unexpected text '{n}'" for n in absent if n in out]
    print(f"[{'PASS' if not problems else 'FAIL'}] {name}: exit {code}")
    for p in problems:
        print(f"         !! {p}\n{out[:700]}")
        failures.append(f"{name}: {p}")


scenario("00 the site names exactly the release's addresses", 0, ["Release rel-a", "the entry script names this release's contract addresses (5 of 5)",
                                                              "publishes no file manifest", "MATCHES"],
         absent=["rank", "Names on chain", "Release on chain"])  # no chain is read unless asked for
scenario("01 a release with a file manifest: files and addresses both match", 0, ["the files match this release's list (3 of 3)", "MATCHES"],
         build=lambda tmp, site, reg: registry([release("rel-b", "lab", manifest_file="manifest-a.json")]))
scenario("02 the files differ from the manifest though the addresses match", 1, ["the files differ", "does not match"],
         build=lambda tmp, site, reg: (open(os.path.join(site, "assets/style-2.css"), "wb").write(b"body{margin:1px}"),
                                       registry([release("rel-b", "lab", manifest_file="manifest-a.json")]))[1])
scenario("03 the site names other contracts (a copy pointed at its own deployment)", 1, ["names other contracts", "does not match"],
         build=lambda tmp, site, reg: (shutil.rmtree(site), write_site(site, site_files(OTHER)), reg)[2])
scenario("04 two releases: one matches, one does not (both are shown, exit 0)", 0, ["Release rel-a", "Release rel-x", "MATCHES", "does not match"],
         build=lambda tmp, site, reg: registry([release("rel-a"), release("rel-x", fp="fp-other.json")]))
scenario("05 only the release asked for is judged", 0, ["Release rel-a"], absent=["Release rel-x"],
         build=lambda tmp, site, reg: registry([release("rel-a"), release("rel-x", fp="fp-other.json")]), extra=("--release", "rel-a"))
scenario("06 an unknown release id", 2, ["unknown release id"], extra=("--release", "nope"))
scenario("07 the site cannot be read (empty directory)", 3, ["INCOMPLETE"],
         build=lambda tmp, site, reg: (shutil.rmtree(site), os.makedirs(site), reg)[2])

# ---- the registry is broken: refused, never run
scenario("10 no releases", 2, ["lists no releases"], build=lambda t, s, r: registry([]))
scenario("11 duplicate ids", 2, ["duplicate id"], build=lambda t, s, r: registry([release("rel-a"), release("rel-a")]))
scenario("12 a file outside the registry directory", 2, ["outside the registry directory"],
         build=lambda t, s, r: registry([release("rel-a", fp="../fp-a.json")]))
scenario("13 a file that does not exist", 2, ["not a file"], build=lambda t, s, r: registry([release("rel-a", fp="missing.json")]))
scenario("14 a missing fingerprint", 2, ["addressFingerprint"],
         build=lambda t, s, r: (lambda x: (x["frontend"].pop("addressFingerprint"), registry([x]))[1])(release("rel-a")))
scenario("15 wrong kind", 2, ["kind"], build=lambda t, s, r: dict(registry([release("rel-a")]), kind="other"))
scenario("16 bad publisher kind", 2, ["publisher"],
         build=lambda t, s, r: registry([dict(release("rel-a"), publisher={"name": "x", "kind": "boss"})]))
scenario("17 a source without a 40-digit commit", 2, ["commit"],
         build=lambda t, s, r: registry([dict(release("rel-a"), source={"repo": "x/y", "commit": "abc"})]))
scenario("18 an id with a slash", 2, ["bad id"], build=lambda t, s, r: registry([release("../x")]))

# ---- JSON output
tmp = tempfile.mkdtemp(prefix="verify-test-")
try:
    site = os.path.join(tmp, "site")
    write_site(site, site_files(ADDRS))
    shutil.copy(REAL_REF, os.path.join(tmp, "ref.json"))
    json.dump(fingerprint(ADDRS, "A"), open(os.path.join(tmp, "fp-a.json"), "w"))
    code, out = run(tmp, registry([release("rel-a")]), site, ("--json",))
    d = json.loads(out)
    ok = code == 0 and d["releases"][0]["matched"] and d["releases"][0]["facts"]["contractsNamed"]["verdict"] == "MATCH" \
        and d["releases"][0]["facts"]["contractsOnChain"]["verdict"] == "SKIPPED"
    print(f"[{'PASS' if ok else 'FAIL'}] 20 --json output is one JSON document with the facts: exit {code}")
    if not ok:
        failures.append("20 --json output")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} expectation(s) failed:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("all scenarios behaved as expected")
