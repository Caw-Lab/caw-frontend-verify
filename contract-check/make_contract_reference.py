#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Build a contract reference (format v1) for the CAW testnet.

Published addresses come from the upstream repo (deployments.ts, addresses.ts at a given commit).
Addresses the repo does not list (cap oracle, path-way expander, endpoint, ...) are read from the
chain on the day the file is made and marked basis "observed" / "external": they pin today's state,
so a later change is detected, but they are not independent proof that the value is the right one.
Read-only: eth_call / eth_getCode only.
"""
import importlib.util
import json
import re
import sys
import urllib.request

spec = importlib.util.spec_from_file_location("cc", "chain_check_prototype.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

UPSTREAM = "https://raw.githubusercontent.com/GilgameshCaw/Caw"
COMMIT = "97cd13f3a1423f702d411472fdd2b2a2e7bfbd59"  # the release the reference is made for


def git_show(path):
    """A file of the upstream repository at the fixed commit (public, so anyone can repeat this)."""
    req = urllib.request.Request(f"{UPSTREAM}/{COMMIT}/{path}", headers={"user-agent": "contract-checker/0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def published():
    src = git_show("client/src/abi/deployments.ts")
    block = src[src.index("testnet: {"):src.index("mainnet: {")]
    out, chain = {}, None
    for line in block.splitlines():
        m = re.match(r"\s+(L1|L2|L2b): \{", line)
        if m:
            chain = m.group(1)
            out[chain] = {}
            continue
        m = re.match(r"\s+(\w+): '(0x[0-9a-fA-F]{40})'", line)
        if m and chain:
            out[chain][m.group(1)] = m.group(2).lower()
    m = re.search(r'CAW_PROFILE_LENS_ADDRESS = "(0x[0-9a-fA-F]{40})"', git_show("client/src/abi/addresses.ts"))
    if m:  # deployments.ts at this commit does not list the Lens
        out["L1"]["CawProfileLens"] = m.group(1).lower()
    return out


CHAINS = {
    "L1": {"chainId": 11155111, "eid": 40161},
    "L2": {"chainId": 84532, "eid": 40245},
    "L2b": {"chainId": 421614, "eid": 40231},
}
ZERO = "0x" + "0" * 40


def main(out_path):
    pub = published()
    contracts = {ch: {n: {"address": a, "basis": "published"} for n, a in sorted(cs.items())} for ch, cs in pub.items()}

    def getaddr(ch, name, sig):
        a = cc.as_addr(cc.call(ch, pub[ch][name], sig))
        assert a and a != ZERO, f"{ch}.{name}.{sig} gave {a}"
        return a

    def add(ch, name, addr, basis):
        contracts[ch][name] = {"address": addr, "basis": basis}

    # observed from the chain
    add("L1", "PathwayExpander", getaddr("L1", "CawProfileMinter", "pathwayExpander()"), "observed")
    add("L1", "CawL1PriceReader", getaddr("L1", "CawProfile", "priceReader()"), "observed")
    add("L1", "SwapRouter", getaddr("L1", "CawProfileMinter", "swapRouter()"), "external")
    add("L1", "WETH", getaddr("L1", "CawProfileMinter", "WETH()"), "external")
    for ch in ("L1", "L2", "L2b"):
        add(ch, "LayerZeroEndpoint", getaddr(ch, "CawProfileLedger", "endpoint()"), "external")
        add(ch, "CawCapOracle", getaddr(ch, "CawActions", "capOracle()"), "observed")
    for ch in ("L2", "L2b"):
        add(ch, "PathwayExpander", getaddr(ch, "CawActionsArchive", "owner()"), "observed")
    zk = cc.as_addr(cc.call("L2", pub["L2"]["CawActions"], "zkVerifier()"))
    assert zk and zk != ZERO
    add("L2", "SP1Verifier", zk, "external")

    rules = []

    def link(ch, name, call, tch, tname):
        rules.append({"type": "link", "chain": ch, "contract": name, "call": call, "target": {"chain": tch, "contract": tname}})

    def zero(ch, name, call):
        rules.append({"type": "zero", "chain": ch, "contract": name, "call": call})

    def value(ch, name, call, expect):
        rules.append({"type": "value", "chain": ch, "contract": name, "call": call, "expect": expect})

    # L1 contracts
    for call, t in [("CAW()", "MintableCaw"), ("cawProfileLedger()", "CawProfileLedger"), ("minter()", "CawProfileMinter"),
                    ("uriGenerator()", "CawProfileURI"), ("networkManager()", "CawNetworkManager"),
                    ("buyAndBurn()", "CawBuyAndBurn"), ("priceReader()", "CawL1PriceReader"), ("owner()", "PathwayExpander")]:
        link("L1", "CawProfile", call, "L1", t)
    for call, t in [("cawProfile()", "CawProfile"), ("minter()", "CawProfileMinter"), ("buyAndBurnAddress()", "CawBuyAndBurn")]:
        link("L1", "CawNetworkManager", call, "L1", t)
    for call, t in [("pathwayExpander()", "PathwayExpander"), ("swapRouter()", "SwapRouter"), ("WETH()", "WETH")]:
        link("L1", "CawProfileMinter", call, "L1", t)
    link("L1", "CawProfileLens", "cawProfile()", "L1", "CawProfile")
    link("L1", "CawProfileLens", "cawProfileMinter()", "L1", "CawProfileMinter")
    link("L1", "CawProfileQuoter", "cawProfile()", "L1", "CawProfile")
    link("L1", "CawProfileMarketplace", "cawProfile()", "L1", "CawProfile")
    link("L1", "CawProfileURI", "fontDataA()", "L1", "CawFontDataA")
    link("L1", "CawProfileURI", "fontDataB()", "L1", "CawFontDataB")
    link("L1", "CawBuyAndBurn", "cawProfile()", "L1", "CawProfile")
    link("L1", "CawBuyAndBurn", "CAW()", "L1", "MintableCaw")

    # every storage chain (L1 co-deploy, L2, L2b)
    for ch in ("L1", "L2", "L2b"):
        if ch == "L1":
            link(ch, "CawProfileLedger", "cawProfile()", "L1", "CawProfile")
            value(ch, "CawProfileLedger", "bypassLZ()", 1)
            value(ch, "CawProfileLedger", "layer1EndpointId()", CHAINS["L2"]["eid"])  # deploy.js passes the peer L2's eid
        else:
            zero(ch, "CawProfileLedger", "cawProfile()")  # cross-chain ledgers keep the L1 link as a LayerZero peer
            value(ch, "CawProfileLedger", "bypassLZ()", 0)
            value(ch, "CawProfileLedger", "layer1EndpointId()", CHAINS["L1"]["eid"])
        link(ch, "CawProfileLedger", "cawActions()", ch, "CawActions")
        link(ch, "CawProfileLedger", "erc1271Sibling()", ch, "CawActionsERC1271")
        link(ch, "CawProfileLedger", "capOracle()", ch, "CawCapOracle")
        link(ch, "CawProfileLedger", "endpoint()", ch, "LayerZeroEndpoint")
        zero(ch, "CawProfileLedger", "owner()")
        link(ch, "CawActions", "cawProfile()", ch, "CawProfileLedger")
        link(ch, "CawActions", "externalSelf()", ch, "CawActions")
        link(ch, "CawActions", "erc1271Sibling()", ch, "CawActionsERC1271")
        link(ch, "CawActions", "capOracle()", ch, "CawCapOracle")
        if ch == "L2":
            link(ch, "CawActions", "zkVerifier()", ch, "SP1Verifier")
        else:
            zero(ch, "CawActions", "zkVerifier()")
        link(ch, "CawActionsERC1271", "cawActions()", ch, "CawActions")
        link(ch, "CawActionsERC1271", "cawProfile()", ch, "CawProfileLedger")
    for ch in ("L2", "L2b"):
        link(ch, "CawChallengeRelay", "cawActions()", ch, "CawActions")
        link(ch, "CawActionsArchive", "owner()", ch, "PathwayExpander")
        link(ch, "CawChallengeRelay", "owner()", ch, "PathwayExpander")

    # LayerZero peers
    for frm, name, to, tname in [("L1", "CawProfile", "L2", "CawProfileLedger"), ("L1", "CawProfile", "L2b", "CawProfileLedger"),
                                 ("L2", "CawProfileLedger", "L1", "CawProfile"), ("L2b", "CawProfileLedger", "L1", "CawProfile")]:
        rules.append({"type": "peer", "chain": frm, "contract": name, "eid": CHAINS[to]["eid"], "target": {"chain": to, "contract": tname}})

    # endpoint delegates
    def delegate(ch, name, tch, tname):
        rules.append({"type": "delegate", "chain": ch, "contract": name,
                      "endpoint": {"chain": ch, "contract": "LayerZeroEndpoint"}, "target": {"chain": tch, "contract": tname}})
    for nm in ("CawProfile", "CawProfileLedger"):
        delegate("L1", nm, "L1", "PathwayExpander")
    for ch in ("L2", "L2b"):
        for nm in ("CawProfileLedger", "CawActionsArchive", "CawChallengeRelay"):
            delegate(ch, nm, ch, "PathwayExpander")

    ref = {
        "schemaVersion": 1,
        "kind": "caw-contract-reference",
        "network": "testnet",
        "release": f"upstream GilgameshCaw/Caw commit {COMMIT[:8]} (master, 2026-09-21)",
        "createdAt": "2026-11-13",
        "notes": [
            "basis 'published': listed in the repo's deployments.ts / addresses.ts at the release above.",
            "basis 'observed': read from the chain on createdAt; pins that day's state (detects later change), not independent proof.",
            "basis 'external': a third-party contract (LayerZero endpoint, SP1 verifier, swap router, WETH) pinned the same way.",
        ],
        "chains": CHAINS,
        "contracts": contracts,
        "rules": rules,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ref, f, indent=1, ensure_ascii=False)
        f.write("\n")
    n = sum(len(v) for v in contracts.values())
    print(f"wrote {out_path}: {n} contracts, {len(rules)} rules")


if __name__ == "__main__":
    main(sys.argv[1])
