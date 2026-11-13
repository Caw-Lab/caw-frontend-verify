#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Independent recompile of the CAW contracts and comparison with the chains.

Runs in a scratch directory. Steps:
  1. check the source checkout is the expected commit
  2. fetch the npm dependencies named in solidity/package-lock.json and verify their sha512 integrity
  3. fetch the official solc binary and verify its sha256 against the official list
  4. compile each contract file (viaIR, optimizer runs=1, evm cancun) with that solc
  5. compare the compiled runtime code with the code on every chain where the reference lists that name
     (immutable and library-link regions taken from solc's own output are zeroed on both sides)
Read-only towards the chains (eth_getCode through the checker module).
usage: recompile.py <scratch-dir> <reference.json> <expected-commit-prefix>
"""
import base64
import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tarfile
import time
import urllib.request

SCRATCH, REF, COMMIT = sys.argv[1], sys.argv[2], sys.argv[3]
SOL = os.path.join(SCRATCH, "src", "solidity")
LOG = open(os.path.join(SCRATCH, "recompile.log"), "a", buffering=1)


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.write(msg + "\n")


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"user-agent": "caw-frontend-verify/0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# 1. checkout
head = subprocess.run(["git", "-C", SCRATCH + "/src", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
assert head.startswith(COMMIT), f"checkout is {head}, expected {COMMIT}"
log("source commit:", head)
assert os.path.isdir(SOL), "solidity/ not found in the scratch directory"

# 2. dependencies from the lock file, with integrity check
lock = json.load(open(os.path.join(SOL, "package-lock.json")))["packages"]
WANT = ["@openzeppelin/contracts", "@openzeppelin/contracts-upgradeable", "@layerzerolabs/lz-evm-protocol-v2",
        "@layerzerolabs/lz-evm-oapp-v2", "@layerzerolabs/lz-evm-messagelib-v2", "@layerzerolabs/oapp-evm",
        "@layerzerolabs/oft-evm", "solidity-bytes-utils"]
deps_info = {}
for name in WANT:
    ent = lock.get("node_modules/" + name)
    assert ent and ent.get("resolved") and ent.get("integrity"), f"{name} not pinned in the lock file"
    algo, b64 = ent["integrity"].split("-", 1)
    data = get(ent["resolved"], timeout=300)
    got = base64.b64encode(hashlib.new(algo, data).digest()).decode()
    assert got == b64, f"integrity mismatch for {name}"
    dest = os.path.join(SOL, "node_modules", name)
    os.makedirs(dest, exist_ok=True)
    tgz = os.path.join(SCRATCH, "dl.tgz")
    open(tgz, "wb").write(data)
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if not m.name.startswith("package/"):
                continue
            m.name = m.name[len("package/"):]
            if m.isfile() or m.isdir():
                t.extract(m, dest, filter="data")
    deps_info[name] = {"version": ent["version"], "integrity": ent["integrity"]}
    log(f"dependency {name}@{ent['version']}: sha512 integrity verified")

# 3. official solc
lst = json.loads(get("https://binaries.soliditylang.org/linux-amd64/list.json"))
b = next(x for x in lst["builds"] if x["version"] == "0.8.30")
solc_path = os.path.join(SCRATCH, "solc")
bin_data = get("https://binaries.soliditylang.org/linux-amd64/" + b["path"], timeout=300)
assert "0x" + hashlib.sha256(bin_data).hexdigest() == b["sha256"], "solc sha256 differs from the official list"
open(solc_path, "wb").write(bin_data)
os.chmod(solc_path, 0o755)
ver = subprocess.run([solc_path, "--version"], capture_output=True, text=True).stdout.strip().splitlines()[-1]
log("solc:", ver, "| sha256 verified against the official list:", b["sha256"])

# 4+5. compile and compare
spec = importlib.util.spec_from_file_location("cc", os.path.join(SCRATCH, "chain_check_prototype.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)
ref = json.load(open(REF))
by_name = {}
for ch, cs in ref["contracts"].items():
    for nm in cs:
        by_name.setdefault(nm, []).append(ch)
sources_present = [nm for nm in sorted(by_name) if os.path.exists(os.path.join(SOL, "contracts", nm + ".sol"))]
log("contracts with a source file in the repo:", len(sources_present), "|", ", ".join(sources_present))

SETTINGS = {"viaIR": True, "optimizer": {"enabled": True, "runs": 1}, "evmVersion": "cancun",
            "outputSelection": {"*": {"*": ["metadata", "evm.deployedBytecode.object",
                                            "evm.deployedBytecode.immutableReferences",
                                            "evm.deployedBytecode.linkReferences"]}}}


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    os.nice(19)


def zero(code, regions):
    bb = bytearray(code)
    for s, n in regions:
        if s + n > len(bb):
            raise ValueError("region outside")
        bb[s:s + n] = b"\x00" * n
    return bytes(bb)


out = {"commit": head, "solc": ver, "solcSha256": b["sha256"], "settings": {k: v for k, v in SETTINGS.items() if k != "outputSelection"},
       "dependencies": deps_info, "results": {}}
for nm in sources_present:
    t0 = time.time()
    inp = {"language": "Solidity", "sources": {f"contracts/{nm}.sol": {"urls": [f"contracts/{nm}.sol"]}}, "settings": SETTINGS}
    p = subprocess.run([solc_path, "--standard-json", "--base-path", SOL, "--include-path", os.path.join(SOL, "node_modules"),
                        "--allow-paths", SOL], input=json.dumps(inp), capture_output=True, text=True, preexec_fn=limit)
    try:
        res = json.loads(p.stdout)
    except Exception:
        log(f"{nm}: solc gave no JSON (exit {p.returncode}): {p.stderr[-300:]}")
        out["results"][nm] = {"status": "compile-failed"}
        continue
    errs = [e for e in res.get("errors", []) if e.get("severity") == "error"]
    if errs:
        log(f"{nm}: compile errors: {errs[0].get('formattedMessage', '')[:300]}")
        out["results"][nm] = {"status": "compile-failed"}
        continue
    c = res["contracts"][f"contracts/{nm}.sol"][nm]["evm"]["deployedBytecode"]
    imm = sorted([r["start"], r["length"]] for v in (c.get("immutableReferences") or {}).values() for r in v)
    lnk = sorted([r["start"], r["length"]] for v in (c.get("linkReferences") or {}).values() for libs in v.values() for r in libs) \
        if c.get("linkReferences") else []
    obj = c["object"]
    # library placeholders are text like __$...$__; every link region becomes zero bytes
    raw = bytearray(len(obj) // 2)
    for i in range(0, len(obj), 2):
        pair = obj[i:i + 2]
        raw[i // 2] = int(pair, 16) if all(ch in "0123456789abcdefABCDEF" for ch in pair) else 0
    compiled = bytes(raw)
    cbor_len = int.from_bytes(compiled[-2:], "big") + 2
    entry = {"status": "compiled", "length": len(compiled), "seconds": round(time.time() - t0, 1),
             "immutableRegions": imm, "linkRegions": lnk, "perChain": {}}
    for ch in by_name[nm]:
        a = ref["contracts"][ch][nm]["address"]
        chain_code = bytes.fromhex(cc.rpc(ch, "eth_getCode", [a, "latest"])["result"][2:])
        if len(chain_code) != len(compiled):
            entry["perChain"][ch] = {"result": "length-differs", "chainLength": len(chain_code)}
            continue
        regs = imm + lnk
        eq = zero(chain_code, regs) == zero(compiled, regs)
        eq_nocbor = zero(chain_code, regs + [[len(compiled) - cbor_len, cbor_len]]) == zero(compiled, regs + [[len(compiled) - cbor_len, cbor_len]])
        first = None
        if not eq:
            za, zb = zero(chain_code, regs), zero(compiled, regs)
            first = next(i for i in range(len(za)) if za[i] != zb[i])
        entry["perChain"][ch] = {
            "result": "identical" if eq else ("identical-except-metadata" if eq_nocbor else "DIFFERS"),
            "maskedHash": "0x" + cc.keccak256(zero(compiled, regs)).hex(), "firstDifferingByte": first}
    out["results"][nm] = entry
    log(f"{nm}: compiled in {entry['seconds']}s, {len(compiled)} bytes; " + "; ".join(f"{ch}={v['result']}" for ch, v in entry["perChain"].items()))
    json.dump(out, open(os.path.join(SCRATCH, "recompile_result.json"), "w"), indent=1)

json.dump(out, open(os.path.join(SCRATCH, "recompile_result.json"), "w"), indent=1)
open(os.path.join(SCRATCH, "DONE"), "w").write("done\n")
log("finished")
