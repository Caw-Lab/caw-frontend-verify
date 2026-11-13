#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""What is on the chains at addresses a site names that a release does not list.

  site_address_probe.py --reference REF.json --address 0x… [--address 0x…] [--json]

For every address, in order on each chain of the reference: is there contract code, and is it the same
code (ignoring the values the constructor embeds) as one of the release's own contracts on that chain?
It reads only (eth_getCode). It does not say what a contract does or whether it is the one a node
really uses; it says what is there.

Verdict:  MATCH         every address carries the same code as a contract of the release
          DIFFERENT     at least one address has other code, or none
          NOT_AVAILABLE no address was given
          ERROR         the chains could not be read
Exit code: 0 MATCH or NOT_AVAILABLE, 1 DIFFERENT, 2 bad input, 3 ERROR.
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cc", os.path.join(HERE, "chain_check_prototype.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
MAX_ADDRESSES = 60


class Invalid(Exception):
    pass


def candidates(ref):
    """{chain: [(name, maskedHash, mask)]} for the release's contracts that carry a code pin."""
    out = {}
    for chain, cs in ref.get("contracts", {}).items():
        for name, info in cs.items():
            pin = info.get("code") if isinstance(info, dict) else None
            if isinstance(pin, dict) and isinstance(pin.get("maskedHash"), str) and isinstance(pin.get("mask"), list):
                out.setdefault(chain, []).append((name, pin["maskedHash"].lower(), pin["mask"]))
    return out


def same_as(code, chain_cands):
    for name, h, mask in chain_cands:
        try:
            masked = cc.zero_regions(code, mask)
        except ValueError:
            continue  # the pin does not fit this code
        if "0x" + cc.keccak256(masked).hex() == h:
            return name
    return None


def get_code(chain, addr):
    res = cc.rpc(chain, "eth_getCode", [addr, "latest"])
    if not isinstance(res, dict) or "error" in res or not isinstance(res.get("result"), str):
        raise RuntimeError("the chain did not answer")
    h = res["result"]
    if not re.fullmatch(r"0x([0-9a-fA-F]{2})*", h):
        raise RuntimeError("the chain answered with something that is not code")
    return bytes.fromhex(h[2:])


def probe(ref, addresses):
    seen, addrs = set(), []
    for a in addresses:
        if not isinstance(a, str) or not ADDR.match(a):
            raise Invalid(f"not an address: {str(a)[:60]}")
        if a.lower() not in seen:
            seen.add(a.lower())
            addrs.append(a.lower())
    if len(addrs) > MAX_ADDRESSES:
        raise Invalid(f"too many addresses ({len(addrs)}; at most {MAX_ADDRESSES})")
    if not addrs:
        return {"tool": "probe", "verdict": "NOT_AVAILABLE", "reason": "the site names no address outside the release", "checked": 0, "addresses": []}
    chains = list(ref.get("chains", {}))
    cands = candidates(ref)
    rows, unreadable = [], 0
    for a in addrs:
        found, errors = [], 0
        for ch in chains:
            try:
                code = get_code(ch, a)
            except RuntimeError:
                errors += 1
                continue
            if code:
                found.append({"chain": ch, "bytes": len(code), "sameAs": same_as(code, cands.get(ch, []))})
        if errors == len(chains):
            unreadable += 1
            rows.append({"address": a, "status": "unreadable"})
        elif any(f["sameAs"] for f in found):
            f = next(f for f in found if f["sameAs"])
            rows.append({"address": a, "status": "same-code", "chain": f["chain"], "bytes": f["bytes"], "sameAs": f["sameAs"]})
        elif found:
            rows.append({"address": a, "status": "other-code", "chain": found[0]["chain"], "bytes": found[0]["bytes"], "sameAs": None})
        else:
            rows.append({"address": a, "status": "no-code" if not errors else "unreadable"})
            unreadable += 1 if errors else 0
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    out = {"tool": "probe", "checked": len(rows), "sameCode": count("same-code"), "otherCode": count("other-code"),
           "noCode": count("no-code"), "unreadable": count("unreadable"), "addresses": rows}
    if unreadable:
        out["verdict"] = "ERROR"
        out["reason"] = f"{unreadable} address(es) could not be read on the chains"
    elif out["sameCode"] == len(rows):
        out["verdict"] = "MATCH"
    else:
        out["verdict"] = "DIFFERENT"
    return out


def text(res):
    lines = [f"Addresses checked: {res.get('checked', 0)}  ->  {res['verdict']}"]
    if res.get("reason"):
        lines.append(f"  {res['reason']}")
    for r in res.get("addresses", []):
        if r["status"] == "same-code":
            lines.append(f"  {r['address']}  {r['chain']}: same code as the release's {r['sameAs']}")
        elif r["status"] == "other-code":
            lines.append(f"  {r['address']}  {r['chain']}: contract code ({r['bytes']} bytes) that is none of the release's")
        elif r["status"] == "no-code":
            lines.append(f"  {r['address']}  no contract code on any chain of the reference")
        else:
            lines.append(f"  {r['address']}  could not be read")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reference", required=True)
    ap.add_argument("--address", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        ref = cc.load_reference(a.reference)
        res = probe(ref, a.address)
    except Invalid as e:
        print(json.dumps({"tool": "probe", "verdict": "INVALID", "reason": str(e)}) if a.json else f"INVALID: {e}")
        return 2
    except (OSError, ValueError) as e:
        msg = f"cannot read the reference: {type(e).__name__}"
        print(json.dumps({"tool": "probe", "verdict": "INVALID", "reason": msg}) if a.json else f"INVALID: {msg}")
        return 2
    except RuntimeError as e:
        print(json.dumps({"tool": "probe", "verdict": "ERROR", "reason": str(e)[:160]}) if a.json else f"ERROR: {e}")
        return 3
    print(json.dumps(res) if a.json else text(res))
    return {"MATCH": 0, "NOT_AVAILABLE": 0, "DIFFERENT": 1, "ERROR": 3}[res["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
