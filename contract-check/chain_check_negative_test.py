#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Negative tests for the contract checker (reference format v1).

A deliberately broken reference must not pass. Read-only: eth_chainId / eth_getCode / eth_call only.
usage: python3 chain_check_negative_test_v2.py <contract-reference.json>
"""
import copy
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("cc", "chain_check_prototype.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

BASE = cc.load_reference(sys.argv[1])
MAINNET_CAW = "0xf3b9569f82b18aef890de263b84189bd33ebe452"  # exists on Ethereum mainnet only
failures = []


def addr(r, ch, nm):
    return r["contracts"][ch][nm]["address"]


def setaddr(r, ch, nm, a):
    r["contracts"][ch][nm]["address"] = a


def flip(a):
    return a[:-1] + ("0" if a[-1] != "0" else "1")


def has(results, status, needle):
    return any(s == status and needle in t for s, t in results)


def scenario(name, mutate, expect, want, rpc_patch=None):
    ref = copy.deepcopy(BASE)
    mutate(ref)
    saved = dict(cc.RPC)
    if rpc_patch:
        cc.RPC.update(rpc_patch)
    try:
        results, v = cc.run_checks(ref)
    finally:
        cc.RPC.clear()
        cc.RPC.update(saved)
    problems = []
    if v != want:
        problems.append(f"verdict {v}, expected {want}")
    for status, needle in expect:
        if not has(results, status, needle):
            problems.append(f"missing {status} for '{needle}'")
    flagged = [(s, t) for s, t in results if s in cc.BAD or s == "INVALID"]
    print(f"[{'PASS' if not problems else 'FAIL'}] {name}: verdict {v} ({len(flagged)} flagged)")
    for s, t in flagged[:3]:
        print(f"         {s}: {t[:140]}")
    for pr in problems:
        print(f"         !! {pr}")
        failures.append(f"{name}: {pr}")


# ---- control
scenario("00 control: the real reference", lambda r: None, [], "PASS")

# ---- addresses that are wrong
def swap(r):
    a, b = addr(r, "L1", "CawProfileMinter"), addr(r, "L1", "CawProfileQuoter")
    setaddr(r, "L1", "CawProfileMinter", b)
    setaddr(r, "L1", "CawProfileQuoter", a)
scenario("01 two addresses swapped (Minter <-> Quoter)", swap,
         [("MISMATCH", "L1.CawProfile.minter()"), ("MISMATCH", "L1.CawNetworkManager.minter()"),
          ("MISMATCH", "L1.CawProfileLens.cawProfileMinter()")], "FAIL")
scenario("02 lookalike address (one hex digit)", lambda r: setaddr(r, "L2", "CawActions", flip(addr(r, "L2", "CawActions"))),
         [("NOCODE", "L2.CawActions "), ("MISMATCH", "L2.CawProfileLedger.cawActions()")], "FAIL")
scenario("03 cross-chain mix-up (L2b ledger listed as the L2 ledger)",
         lambda r: setaddr(r, "L2", "CawProfileLedger", addr(r, "L2b", "CawProfileLedger")),
         [("NOCODE", "L2.CawProfileLedger "), ("MISMATCH", "L1.CawProfile.peers(eid 40245)")], "FAIL")
scenario("04 token from another chain (mainnet CAW listed as the Sepolia token)",
         lambda r: setaddr(r, "L1", "MintableCaw", MAINNET_CAW),
         [("NOCODE", "L1.MintableCaw "), ("MISMATCH", "L1.CawProfile.CAW()")], "FAIL")
scenario("05 wrong chain behind an RPC (L2 read through an Arbitrum RPC)", lambda r: None,
         [("MISMATCH", "L2: eth_chainId")], "FAIL", rpc_patch={"L2": (cc.RPC["L2b"][0], None)})

# ---- values that used to be informational only
scenario("06 cap oracle replaced by another real contract (L2)",
         lambda r: setaddr(r, "L2", "CawCapOracle", addr(r, "L2", "CawActionsERC1271")),
         [("MISMATCH", "L2.CawProfileLedger.capOracle()"), ("MISMATCH", "L2.CawActions.capOracle()")], "FAIL")
scenario("07 expander replaced by another real contract (L1)",
         lambda r: setaddr(r, "L1", "PathwayExpander", addr(r, "L1", "CawProfileMinter")),
         [("MISMATCH", "L1.CawProfile.owner()"), ("MISMATCH", "L1.CawProfileMinter.pathwayExpander()"),
          ("MISMATCH", "delegates(L1.CawProfile)")], "FAIL")
def zk_zero(r):
    r["rules"] = [x for x in r["rules"] if not (x["type"] == "link" and x["chain"] == "L2" and x["call"] == "zkVerifier()")]
    r["rules"].append({"type": "zero", "chain": "L2", "contract": "CawActions", "call": "zkVerifier()"})
scenario("08 ZK verifier unexpectedly set (reference says off on L2)", zk_zero, [("MISMATCH", "L2.CawActions.zkVerifier()")], "FAIL")
def peer_wrong(r):
    for x in r["rules"]:
        if x["type"] == "peer" and x["chain"] == "L1" and x["eid"] == 40245:
            x["target"] = {"chain": "L2b", "contract": "CawProfileLedger"}
scenario("09 LayerZero peer pointing at the wrong ledger", peer_wrong, [("MISMATCH", "L1.CawProfile.peers(eid 40245)")], "FAIL")
def bypass_wrong(r):
    for x in r["rules"]:
        if x["type"] == "value" and x["chain"] == "L2" and x["call"] == "bypassLZ()":
            x["expect"] = 1
scenario("10 bypass flag differs from the reference (L2)", bypass_wrong, [("MISMATCH", "L2.CawProfileLedger.bypassLZ()")], "FAIL")

# ---- the reference itself is broken: it must be refused, never passed
scenario("11 entry removed that rules still refer to", lambda r: r["contracts"]["L2"].pop("CawActionsERC1271"),
         [("INVALID", "L2.CawActionsERC1271")], "INVALID")
scenario("12 zero address as a contract", lambda r: setaddr(r, "L1", "CawNetworkManager", "0x" + "0" * 40),
         [("INVALID", "zero address")], "INVALID")
scenario("13 malformed address", lambda r: setaddr(r, "L1", "CawProfile", "0x1234"), [("INVALID", "20-byte")], "INVALID")
scenario("14 unknown schema version", lambda r: r.__setitem__("schemaVersion", 2), [("INVALID", "schemaVersion")], "INVALID")
scenario("15 unknown rule type", lambda r: r["rules"].append({"type": "magic", "chain": "L1", "contract": "CawProfile"}),
         [("INVALID", "unknown type")], "INVALID")
scenario("16 rule names a contract that is not listed (typo)",
         lambda r: r["rules"].append({"type": "zero", "chain": "L1", "contract": "CawProfil", "call": "owner()"}),
         [("INVALID", "CawProfil")], "INVALID")
scenario("17 empty rules (a reference that checks nothing)", lambda r: r.__setitem__("rules", []), [("INVALID", "rules missing")], "INVALID")
scenario("18 empty contracts", lambda r: r.__setitem__("contracts", {}), [("INVALID", "contracts missing")], "INVALID")
scenario("19 missing basis on an address", lambda r: r["contracts"]["L1"]["CawProfile"].pop("basis"), [("INVALID", "basis")], "INVALID")

# ---- code (bytecode) scenarios
def pin(r, ch, nm): return r["contracts"][ch][nm]["code"]

def code_changed(r):
    h = pin(r, "L1", "CawProfileQuoter")["maskedHash"]
    pin(r, "L1", "CawProfileQuoter")["maskedHash"] = h[:-1] + ("0" if h[-1] != "0" else "1")
scenario("20 code differs, everything else equal (hash of one contract changed)", code_changed,
         [("MISMATCH", "L1.CawProfileQuoter code hash")], "FAIL")

def other_code(r):
    a, b = pin(r, "L1", "CawProfileQuoter"), pin(r, "L1", "CawProfileMarketplace")
    a["maskedHash"], b["maskedHash"] = b["maskedHash"], a["maskedHash"]
scenario("21 code pins swapped between two contracts", other_code,
         [("MISMATCH", "L1.CawProfileQuoter code hash"), ("MISMATCH", "L1.CawProfileMarketplace code hash")], "FAIL")

def shifted_mask(r):
    m = pin(r, "L1", "CawProfile")["mask"]
    m[0] = [m[0][0] + 1, m[0][1]]
scenario("22 wrong immutable region (shifted by one byte)", shifted_mask, [("MISMATCH", "L1.CawProfile code hash")], "FAIL")

def mask_outside(r):
    pin(r, "L1", "CawProfileQuoter")["mask"].append([10**6, 32])
scenario("23 region outside the code", mask_outside, [("MISMATCH", "L1.CawProfileQuoter code hash: a masked region lies outside")], "FAIL")

def lib_swapped(r):
    # the reference now says the library is a different (real) contract
    setaddr(r, "L1", "SessionMessageParser", addr(r, "L1", "CawProfileQuoter"))
scenario("24 library replaced by another real contract", lib_swapped,
         [("MISMATCH", "L1.CawProfileLedger linked library"), ("MISMATCH", "L1.SessionMessageParser code hash")], "FAIL")

def lib_unmasked_evil(r):
    # a library address that differs from the one linked in the L2b ledger's code
    setaddr(r, "L2b", "SessionMessageParser", addr(r, "L2", "SessionMessageParser"))
scenario("25 library address of another chain listed for L2b", lib_unmasked_evil,
         [("MISMATCH", "L2b.CawProfileLedger linked library")], "FAIL")

scenario("26 code pin missing", lambda r: r["contracts"]["L1"]["CawProfile"].pop("code"), [("INVALID", "code pin missing")], "INVALID")
scenario("27 unknown evidence", lambda r: pin(r, "L1", "CawProfile").__setitem__("evidence", "trust-me"), [("INVALID", "code.evidence")], "INVALID")
scenario("28 malformed hash", lambda r: pin(r, "L1", "CawProfile").__setitem__("maskedHash", "0x1234"), [("INVALID", "code.maskedHash")], "INVALID")
scenario("29 linked library not listed", lambda r: r["contracts"]["L1"].pop("SessionMessageParser"), [("INVALID", "linked library")], "INVALID")

# ---- recompile provenance
scenario("30 recompile evidence without provenance", lambda r: r.pop("provenance"), [("INVALID", "needs provenance.recompile")], "INVALID")
scenario("31 provenance missing the compiler hash", lambda r: r["provenance"]["recompile"].pop("compilerSha256"), [("INVALID", "compilerSha256")], "INVALID")
scenario("32 older-compiler evidence without its note", lambda r: r["provenance"]["olderCompiler"].pop("MintableCaw"), [("INVALID", "olderCompiler.MintableCaw")], "INVALID")
def downgrade(r):  # claiming recompile evidence for a contract whose code no longer matches
    pin(r, "L2", "CawActionsArchive")["maskedHash"] = pin(r, "L2", "CawActionsArchive")["maskedHash"][:-1] + "0"
scenario("33 recompile-identical pin that no longer matches the chain", downgrade, [("MISMATCH", "L2.CawActionsArchive code hash (recompile-identical)")], "FAIL")

print()
if failures:
    print(f"{len(failures)} expectation(s) failed:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("all scenarios behaved as expected")
