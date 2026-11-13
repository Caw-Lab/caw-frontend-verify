#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Add a 'code' pin (and discovered linked libraries) to every contract of a contract reference.

For each contract: read the runtime code from the chain, zero the immutable regions and the
library-link regions, hash it. Linked libraries are read out of the code, listed as contracts of
their own (basis 'observed') and pinned too; the pin records where each library address sits.
Where Sourcify has a verified build, its regions are used and the recompiled code is compared with
the chain's code by this script (Sourcify's verdict is not taken on trust).

Evidence: sourcify-exact-match | sourcify-match (equal except the CBOR metadata) |
          same-code-as:<chain.name> | observed-only
Read-only: eth_getCode, and HTTPS GET to Sourcify.
"""
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location("cc", "chain_check_prototype.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def sourcify(chain_id, addr):
    url = f"https://sourcify.dev/server/v2/contract/{chain_id}/{addr}?fields=runtimeBytecode,compilation"
    req = urllib.request.Request(url, headers={"user-agent": "caw-frontend-verify/0", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"sourcify HTTP {e.code}")


hexbytes = lambda h: bytes.fromhex(h[2:])


def flat(refs):
    return sorted([r["start"], r["length"]] for v in (refs or {}).values() for r in v)


def link_list(link_refs):
    """{file: {lib: [{start,length}]}} -> [(lib, start, length)]"""
    out = []
    for lib_by_name in (link_refs or {}).values():
        for lib, refs in lib_by_name.items():
            out += [(lib, r["start"], r["length"]) for r in refs]
    return sorted(out, key=lambda x: x[1])


def zero(code, ranges):
    b = bytearray(code)
    for start, length in ranges:
        if start + length > len(b):
            raise ValueError("mask outside code")
        b[start:start + length] = b"\x00" * length
    return bytes(b)


def mhash(code, ranges):
    return "0x" + cc.keccak256(zero(code, ranges)).hex()


def main(src, dst):
    ref = json.load(open(src, encoding="utf-8"))
    for cs in ref["contracts"].values():          # start clean
        for e in cs.values():
            e.pop("code", None)
    cid = {k: v["chainId"] for k, v in ref["chains"].items()}
    done = {}                                      # (chain, name) -> pin dict
    info = {}                                      # (chain, name) -> (code, imm_ranges, links[(lib,start,len)])

    def process(ch, nm):
        a = ref["contracts"][ch][nm]["address"]
        code = hexbytes(cc.rpc(ch, "eth_getCode", [a, "latest"])["result"])
        assert code, f"{ch}.{nm} has no code"
        d = sourcify(cid[ch], a)
        time.sleep(0.15)
        pin = None
        imm, links = [], []
        if d and d.get("runtimeBytecode"):
            rb = d["runtimeBytecode"]
            onchain, recomp = hexbytes(rb["onchainBytecode"]), hexbytes(rb["recompiledBytecode"])
            imm, links = flat(rb.get("immutableReferences")), link_list(rb.get("linkReferences"))
            if onchain != code:
                print(f"  ! {ch}.{nm}: Sourcify's on-chain copy differs from the chain now; ignoring Sourcify")
            else:
                lk = [[s, n] for _, s, n in links]
                cbor = [[v["offset"], (len(v["value"]) - 2) // 2] for v in (rb.get("cborAuxdata") or {}).values()]
                if zero(onchain, imm + lk) == zero(recomp, imm + lk):
                    pin = ("sourcify-exact-match", imm, links)
                elif zero(onchain, imm + lk + cbor) == zero(recomp, imm + lk + cbor):
                    pin = ("sourcify-match", imm, links)
                else:
                    print(f"  ! {ch}.{nm}: Sourcify's recompiled code does not equal the chain code by my comparison")
        info[(ch, nm)] = (code, imm, links)
        done[(ch, nm)] = pin

    # discover contracts, including the libraries they link
    queue = [(ch, nm) for ch, cs in ref["contracts"].items() for nm in sorted(cs)]
    while queue:
        ch, nm = queue.pop(0)
        if (ch, nm) in info:
            continue
        process(ch, nm)
        code, imm, links = info[(ch, nm)]
        for lib, start, n in links:
            addr = "0x" + code[start:start + n].hex()
            known = ref["contracts"][ch].get(lib)
            if known is None:
                ref["contracts"][ch][lib] = {"address": addr, "basis": "observed"}
                queue.append((ch, lib))
            else:
                assert known["address"].lower() == addr.lower(), f"{ch}.{nm}: library {lib} address differs between uses"

    # contracts that Sourcify did not confirm: same code as a Sourcify-confirmed one (regions of that one).
    # A contract matched this way can link a library at its own address on its own chain; add it and
    # try again until nothing changes.
    changed = True
    while changed:
        changed = False
        for (ch, nm), pin in sorted(list(done.items())):
            if pin:
                continue
            code = info[(ch, nm)][0]
            for (och, onm), opin in sorted(done.items()):
                if opin and (och, onm) != (ch, nm):
                    oimm, olinks = opin[1], opin[2]
                    try:
                        rng = oimm + [[s, n] for _, s, n in olinks]
                        if mhash(code, rng) == mhash(info[(och, onm)][0], rng):
                            done[(ch, nm)] = (f"same-code-as:{och}.{onm}", oimm, olinks)
                            changed = True
                            break
                    except ValueError:
                        continue
        for (ch, nm), pin in sorted(list(done.items())):
            if not pin:
                continue
            code = info[(ch, nm)][0]
            for lib, st, n in pin[2]:
                if lib not in ref["contracts"][ch]:
                    ref["contracts"][ch][lib] = {"address": "0x" + code[st:st + n].hex(), "basis": "observed"}
                    process(ch, lib)
                    changed = True

    # write the pins
    counts = {}
    for (ch, nm), pin in sorted(done.items()):
        code, imm, links = info[(ch, nm)]
        if pin:
            evidence, imm, links = pin
        else:
            evidence, imm, links = "observed-only", [], []
        rng = imm + [[s, n] for _, s, n in links]
        entry = {"maskedHash": mhash(code, rng), "mask": imm, "evidence": evidence}
        if links:
            entry["links"] = [{"start": s, "length": n, "target": {"chain": ch, "contract": lib}} for lib, s, n in links]
        ref["contracts"][ch][nm]["code"] = entry
        k = evidence.split(":")[0]
        counts[k] = counts.get(k, 0) + 1
        extra = f"  links: {[l[0] for l in links]}" if links else ""
        print(f"  {ch}.{nm:22} {evidence}{extra}")
    json.dump(ref, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(dst, "a").write("\n")
    print("evidence counts:", counts, "| contracts:", sum(len(v) for v in ref["contracts"].values()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
