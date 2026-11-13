#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Read-only check of the CAW testnet contract links against a reference set.

Original code (no third-party libraries). Only eth_chainId, eth_getCode and
eth_call are sent; nothing is signed or written.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request

# ---------------------------------------------------------------- keccak-256
_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data) + b"\x01"
    while len(padded) % rate:
        padded += b"\x00"
    padded[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        a = _f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out[:32]


def selector(sig: str) -> str:
    return keccak256(sig.encode()).hex()[:8]


# self test with known values
assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
assert selector("transfer(address,uint256)") == "a9059cbb"
assert selector("balanceOf(address)") == "70a08231"

# ---------------------------------------------------------------- JSON-RPC
# Public RPC per chain key (chainId is checked against the reference's own value).
RPC_URL = {
    "L1": "https://ethereum-sepolia-rpc.publicnode.com",
    "L2": "https://base-sepolia-rpc.publicnode.com",
    "L2b": "https://arbitrum-sepolia-rpc.publicnode.com",
}
RPC = {k: (u, None) for k, u in RPC_URL.items()}  # (url, unused); kept for rpc()
_id = [0]


_cache = {}


def rpc(chain, method, params):
    url = RPC[chain][0]
    key = (url, method, json.dumps(params, sort_keys=True))
    if key in _cache:
        return _cache[key]
    res = _rpc_uncached(url, method, params)
    _cache[key] = res
    return res


def _rpc_uncached(url, method, params):
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params}).encode()
    req = urllib.request.Request(url, body, {"content-type": "application/json", "user-agent": "caw-frontend-verify/0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.load(r)
            time.sleep(0.05)
            return res
        except Exception as e:  # retry transient failures
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"rpc failed ({method}): {type(last).__name__}")


def call(chain, to, sig, args=b""):
    data = "0x" + selector(sig) + args.hex()
    res = rpc(chain, "eth_call", [{"to": to, "data": data}, "latest"])
    if "error" in res:
        return None
    out = res.get("result", "0x")
    return out if out and out != "0x" else None


def as_addr(word):
    return None if word is None or len(word) < 66 else "0x" + word[-40:]


def uint32_arg(n):
    return n.to_bytes(32, "big")


# ---------------------------------------------------------------- reference format (v1)
import os

ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
SIG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\((uint32|address)?\)$")
RULE_TYPES = ("link", "zero", "value", "peer", "delegate")
BASES = ("published", "observed", "external")
BAD = ("MISMATCH", "NOCODE", "CALLFAIL")
HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
EVIDENCE = ("recompile-identical", "recompile-except-metadata", "sourcify-exact-match", "sourcify-match", "observed-only")


def is_evidence(ev):
    return isinstance(ev, str) and (ev in EVIDENCE or (ev.startswith("same-code-as:") and "." in ev))


def is_region(m):
    return isinstance(m, list) and len(m) == 2 and all(isinstance(x, int) and x >= 0 for x in m)


def zero_regions(code, regions):
    b = bytearray(code)
    for start, length in regions:
        if start + length > len(b):
            raise ValueError("region outside the code")
        b[start:start + length] = b"\x00" * length
    return bytes(b)


def load_reference(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_reference(ref):
    """Return a list of problems; an empty list means the reference is well formed."""
    p = []
    if not isinstance(ref, dict):
        return ["reference is not an object"]
    if ref.get("schemaVersion") != 1:
        p.append(f"unsupported schemaVersion {ref.get('schemaVersion')!r} (this checker reads 1)")
    if ref.get("kind") != "caw-contract-reference":
        p.append("kind must be 'caw-contract-reference'")
    chains = ref.get("chains")
    contracts = ref.get("contracts")
    rules = ref.get("rules")
    if not isinstance(chains, dict) or not chains:
        p.append("chains missing")
        chains = {}
    for k, c in chains.items():
        if not (isinstance(c, dict) and isinstance(c.get("chainId"), int) and c["chainId"] > 0
                and isinstance(c.get("eid"), int)):
            p.append(f"chain {k}: chainId/eid must be integers")
        if k not in RPC_URL:
            p.append(f"chain {k}: no RPC configured in this checker")
    if not isinstance(contracts, dict) or not contracts:
        p.append("contracts missing")
        contracts = {}
    for ch, cs in contracts.items():
        if ch not in chains:
            p.append(f"contracts: unknown chain {ch}")
            continue
        for name, e in (cs or {}).items():
            if not (isinstance(e, dict) and isinstance(e.get("address"), str) and ADDR.match(e["address"])):
                p.append(f"{ch}.{name}: address is not a 20-byte hex address")
            elif e["address"].lower() == "0x" + "0" * 40:
                p.append(f"{ch}.{name}: zero address is not a contract")
            if isinstance(e, dict) and e.get("basis") not in BASES:
                p.append(f"{ch}.{name}: basis must be one of {BASES}")
            code = e.get("code") if isinstance(e, dict) else None
            if not isinstance(code, dict):
                p.append(f"{ch}.{name}: code pin missing")
            else:
                if not (isinstance(code.get("maskedHash"), str) and HASH.match(code["maskedHash"])):
                    p.append(f"{ch}.{name}: code.maskedHash must be a 32-byte hex hash")
                if not (isinstance(code.get("mask"), list) and all(is_region(m) for m in code["mask"])):
                    p.append(f"{ch}.{name}: code.mask must be a list of [start, length]")
                if not is_evidence(code.get("evidence")):
                    p.append(f"{ch}.{name}: code.evidence must be one of {EVIDENCE} or 'same-code-as:<chain.name>'")
                for lk in code.get("links", []) if isinstance(code.get("links", []), list) else []:
                    if not (isinstance(lk, dict) and is_region([lk.get("start"), lk.get("length")]) and lk.get("length") == 20):
                        p.append(f"{ch}.{name}: code.links entries need start and a 20-byte length")
    for ch, cs in contracts.items():
        for name, e in (cs or {}).items():
            code = e.get("code") if isinstance(e, dict) else None
            for lk in (code.get("links") if isinstance(code, dict) and isinstance(code.get("links"), list) else []):
                tg = lk.get("target") if isinstance(lk, dict) else None
                if not (isinstance(tg, dict) and tg.get("chain") in contracts and tg.get("contract") in (contracts[tg["chain"]] or {})):
                    p.append(f"{ch}.{name}: linked library {tg!r} is not in contracts")
    # evidence from our own recompile needs the conditions it was made under
    prov = ref.get("provenance") if isinstance(ref.get("provenance"), dict) else {}
    rc = prov.get("recompile") if isinstance(prov.get("recompile"), dict) else None
    older = prov.get("olderCompiler") if isinstance(prov.get("olderCompiler"), dict) else {}
    for ch, cs in contracts.items():
        for name, e in (cs or {}).items():
            ev = (e.get("code") or {}).get("evidence") if isinstance(e, dict) else None
            if isinstance(ev, str) and ev.startswith("recompile-"):
                if rc is None or not all(k in rc for k in ("sourceCommit", "compiler", "compilerSha256", "settings", "dependencies")):
                    p.append(f"{ch}.{name}: evidence '{ev}' needs provenance.recompile (sourceCommit, compiler, compilerSha256, settings, dependencies)")
                if ev == "recompile-except-metadata" and name not in older:
                    p.append(f"{ch}.{name}: evidence 'recompile-except-metadata' needs provenance.olderCompiler.{name}")
    if not isinstance(rules, list) or not rules:
        p.append("rules missing")
        rules = []

    def has(ch, nm):
        return ch in contracts and nm in (contracts[ch] or {})

    for i, r in enumerate(rules):
        t = r.get("type") if isinstance(r, dict) else None
        if t not in RULE_TYPES:
            p.append(f"rule {i}: unknown type {t!r}")
            continue
        if not has(r.get("chain"), r.get("contract")):
            p.append(f"rule {i}: contract {r.get('chain')}.{r.get('contract')} is not in contracts")
        if t != "delegate" and not (isinstance(r.get("call"), str) and SIG.match(r["call"])) and t != "peer":
            p.append(f"rule {i}: bad call {r.get('call')!r}")
        if t in ("link", "peer", "delegate"):
            tg = r.get("target") or {}
            if not has(tg.get("chain"), tg.get("contract")):
                p.append(f"rule {i}: target {tg.get('chain')}.{tg.get('contract')} is not in contracts")
        if t == "value" and not isinstance(r.get("expect"), int):
            p.append(f"rule {i}: value rule needs an integer 'expect'")
        if t == "peer" and not isinstance(r.get("eid"), int):
            p.append(f"rule {i}: peer rule needs an integer 'eid'")
        if t == "delegate":
            ep = r.get("endpoint") or {}
            if not has(ep.get("chain"), ep.get("contract")):
                p.append(f"rule {i}: endpoint {ep.get('chain')}.{ep.get('contract')} is not in contracts")
    return p


def verdict(results):
    return "FAIL" if any(s in BAD for s, _ in results) else "PASS"


def run_checks(ref, echo=False):
    """Run the reference's rules against the chains. Returns (results, verdict).

    verdict: INVALID (the reference itself is malformed), FAIL, or PASS.
    """
    problems = validate_reference(ref)
    if problems:
        return [("INVALID", t) for t in problems], "INVALID"
    results = []

    def rec(status, text):
        results.append((status, text))
        if echo:
            print(f"[{status:8}] {text}")

    chains, contracts = ref["chains"], ref["contracts"]
    A = lambda ch, nm: contracts[ch][nm]["address"].lower()
    lbl = {A(ch, nm): f"{ch}.{nm}" for ch in contracts for nm in contracts[ch]}

    for ch, c in chains.items():
        got = int(rpc(ch, "eth_chainId", [])["result"], 16)
        rec("OK" if got == c["chainId"] else "MISMATCH", f"{ch}: eth_chainId {got} (expected {c['chainId']})")
    for ch in contracts:
        for nm in sorted(contracts[ch]):
            a = A(ch, nm)
            raw = rpc(ch, "eth_getCode", [a, "latest"]).get("result", "0x")
            n = (len(raw) - 2) // 2
            if n == 0:
                rec("NOCODE", f"{ch}.{nm} {a}: code 0 bytes")
                continue
            rec("OK", f"{ch}.{nm} {a}: code {n} bytes")
            code = bytes.fromhex(raw[2:])
            pin = contracts[ch][nm]["code"]
            links = pin.get("links", [])
            regions = list(pin["mask"]) + [[lk["start"], lk["length"]] for lk in links]
            try:
                got = "0x" + keccak256(zero_regions(code, regions)).hex()
            except ValueError:
                rec("MISMATCH", f"{ch}.{nm} code hash: a masked region lies outside the {n}-byte code")
                continue
            rec("OK" if got == pin["maskedHash"].lower() else "MISMATCH",
                f"{ch}.{nm} code hash ({pin['evidence']})" + ("" if got == pin["maskedHash"].lower() else f": {got} != {pin['maskedHash']}"))
            for lk in links:
                tg = lk["target"]
                want = A(tg["chain"], tg["contract"])
                at = "0x" + code[lk["start"]:lk["start"] + lk["length"]].hex()
                rec("OK" if at == want else "MISMATCH",
                    f"{ch}.{nm} linked library at byte {lk['start']} -> {at}" + ("" if at == want else f", expected {tg['chain']}.{tg['contract']} {want}"))

    for r in ref["rules"]:
        ch, nm, t = r["chain"], r["contract"], r["type"]
        a = A(ch, nm)
        if t == "peer":
            tag = f"{ch}.{nm}.peers(eid {r['eid']})"
            got = as_addr(call(ch, a, "peers(uint32)", uint32_arg(r["eid"])))
        elif t == "delegate":
            ep = r["endpoint"]
            tag = f"{ep['chain']}.{ep['contract']}.delegates({ch}.{nm})"
            got = as_addr(call(ep["chain"], A(ep["chain"], ep["contract"]), "delegates(address)",
                               bytes(12) + bytes.fromhex(a[2:])))
        else:
            tag = f"{ch}.{nm}.{r['call']}"
            out = call(ch, a, r["call"])
            got = as_addr(out)
        if t == "value":
            out = call(ch, a, r["call"])
            gv = None if out is None else int(out, 16)
            rec("OK" if gv == r["expect"] else ("CALLFAIL" if gv is None else "MISMATCH"),
                f"{tag} -> {gv} (expected {r['expect']})")
            continue
        if t == "zero":
            if got is None:
                rec("CALLFAIL", f"{tag} -> (no value / reverted)")
            else:
                rec("OK" if got == "0x" + "0" * 40 else "MISMATCH", f"{tag} -> {got} (expected zero)")
            continue
        tg = r["target"]
        want = A(tg["chain"], tg["contract"])
        if got is None:
            rec("CALLFAIL", f"{tag} -> (no value / reverted)")
        elif got == want:
            rec("OK", f"{tag} -> {tg['chain']}.{tg['contract']}")
        else:
            rec("MISMATCH", f"{tag} -> {got} ({lbl.get(got, 'not in reference')}), expected {tg['chain']}.{tg['contract']} {want}")
    return results, verdict(results)


def main():
    from collections import Counter
    args = [x for x in sys.argv[1:] if x != "--json"]
    as_json = "--json" in sys.argv[1:]
    if len(args) != 1:
        print("usage: python3 chain_check_prototype.py <contract-reference.json> [--json]", file=sys.stderr)
        sys.exit(2)
    try:
        ref = load_reference(args[0])
    except (OSError, ValueError) as e:
        if as_json:
            print(json.dumps({"tool": "contract-check", "verdict": "INVALID", "reason": f"cannot read the reference: {type(e).__name__}"}))
        else:
            print(f"VERDICT: INVALID: cannot read the reference: {type(e).__name__}")
        sys.exit(2)
    try:
        results, v = run_checks(ref, echo=not as_json)
    except Exception as e:  # a network failure must not look like a pass or a difference
        if as_json:
            print(json.dumps({"tool": "contract-check", "verdict": "INCOMPLETE", "reason": f"{type(e).__name__}: {e}"}))
        else:
            print(f"VERDICT: INCOMPLETE: {type(e).__name__}: {e}")
        sys.exit(3)
    counts = dict(Counter(s for s, _ in results))
    evidence = {}
    if v != "INVALID":
        evidence = dict(Counter(e["code"]["evidence"].split(":")[0] for cs in ref["contracts"].values() for e in cs.values()))
    if as_json:
        print(json.dumps({"tool": "contract-check", "verdict": v, "summary": counts, "codeEvidence": evidence,
                          "flagged": [{"status": s, "text": t} for s, t in results if s in BAD or s == "INVALID"][:50]}))
    else:
        print("\nSUMMARY:", counts, "VERDICT:", v)
        if evidence:
            print("CODE EVIDENCE:", evidence, "(observed-only = pinned from the chain, no source evidence)")
    sys.exit({"PASS": 0, "FAIL": 1, "INVALID": 2}[v])


if __name__ == "__main__":
    main()
