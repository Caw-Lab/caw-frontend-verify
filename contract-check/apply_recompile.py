#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Upgrade a pinned contract reference with the results of the independent recompile.

recompile-identical          the recompiled runtime code equals the chain code (immutable regions and
                             library links taken from solc's own output are zeroed on both sides),
                             metadata included
recompile-except-metadata    equal except the trailing metadata (older compiler / other source text)
The conditions of the recompile are recorded under "provenance".
usage: apply_recompile.py <pinned-reference.json> <recompile_result.json> <out.json>
"""
import json
import sys

ref = json.load(open(sys.argv[1], encoding="utf-8"))
rc = json.load(open(sys.argv[2], encoding="utf-8"))
changed = {"recompile-identical": 0, "kept": 0}
for nm, e in rc["results"].items():
    for ch, v in e.get("perChain", {}).items():
        pin = ref["contracts"][ch][nm]["code"]
        if v["result"] != "identical":
            continue
        links = pin.get("links", [])
        solc_links = sorted([lk["start"], lk["length"]] for lk in links)
        assert solc_links == sorted(e["linkRegions"]), f"{ch}.{nm}: link regions differ between the pin and solc"
        new = {"maskedHash": v["maskedHash"], "mask": e["immutableRegions"], "evidence": "recompile-identical"}
        if links:
            new["links"] = links
        ref["contracts"][ch][nm]["code"] = new
        changed["recompile-identical"] += 1

# MintableCaw (testnet token): equal except metadata, compiled with an older solc (found by the search in find_token2.py)
tok = ref["contracts"]["L1"]["MintableCaw"]["code"]
tok["evidence"] = "recompile-except-metadata"
ref["provenance"] = {
    "recompile": {
        "sourceCommit": rc["commit"],
        "compiler": rc["solc"].replace("Version: ", "").split(".Linux")[0],
        "compilerSha256": rc["solcSha256"],
        "compilerSource": "https://binaries.soliditylang.org/linux-amd64 (sha256 checked against the official list.json)",
        "settings": rc["settings"],
        "dependencies": rc["dependencies"],
        "dependenciesSource": "solidity/package-lock.json at the source commit (sha512 integrity checked)",
        "note": "contracts compiled one file at a time; chain code compared with immutable and library-link regions of solc's output zeroed",
    },
    "olderCompiler": {
        "MintableCaw": {
            "compiler": "0.8.22+commit.4fc1097e",
            "compilerSha256": "0x8be0aeb74fc1b8213292a09a84cb524a403602526df87ecad5f5cd2a7ea7d089",
            "settings": {"viaIR": True, "optimizer": {"enabled": True, "runs": 200}, "evmVersion": "default (shanghai)"},
            "note": "the testnet token's metadata names solc 0.8.22; every version of contracts/MintableCaw.sol in the repo history gives the same runtime code under these settings, except the metadata hash",
        }
    },
}
json.dump(ref, open(sys.argv[3], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
open(sys.argv[3], "a").write("\n")
from collections import Counter
ev = Counter(e["code"]["evidence"].split(":")[0] for cs in ref["contracts"].values() for e in cs.values())
print("pins upgraded:", changed["recompile-identical"], "| evidence now:", dict(ev))
