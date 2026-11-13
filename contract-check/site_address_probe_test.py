#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Tests for site_address_probe.py with a fake chain (no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_address_probe as P  # noqa: E402

cc = P.cc
A1 = "0x" + "11" * 20
A2 = "0x" + "22" * 20
A3 = "0x" + "33" * 20
A4 = "0x" + "44" * 20

BASE = bytes(range(256)) * 4  # 1024 bytes of "release code"
MASK = [[100, 32], [500, 32]]  # the constructor-embedded regions


def with_immutables(code, fill):
    b = bytearray(code)
    for s, n in MASK:
        b[s:s + n] = bytes([fill]) * n
    return bytes(b)


def pin(code, mask=MASK):
    return {"address": "0x" + "ab" * 20, "basis": "published",
            "code": {"maskedHash": "0x" + cc.keccak256(cc.zero_regions(code, mask)).hex(), "mask": mask, "evidence": "observed-only"}}


REF = {"chains": {"L1": {"chainId": 1}, "L2": {"chainId": 2}},
       "contracts": {"L1": {"Profile": pin(with_immutables(BASE, 1))}, "L2": {"Actions": pin(with_immutables(BASE[::-1], 2))}}}


class FakeChain:
    def __init__(self, table, fail=()):
        self.table, self.fail, self.calls = table, set(fail), []

    def __call__(self, chain, method, params):
        self.calls.append((chain, method, params[0]))
        assert method == "eth_getCode", "only reads code"
        if chain in self.fail:
            return {"error": {"message": "x"}}
        c = self.table.get((chain, params[0].lower()), b"")
        return {"result": "0x" + c.hex()}


class TestProbe(unittest.TestCase):
    def run_probe(self, table, addrs, fail=(), ref=REF):
        saved = cc.rpc
        cc.rpc = FakeChain(table, fail)
        try:
            return P.probe(ref, addrs), cc.rpc
        finally:
            cc.rpc = saved

    def test_same_code_with_different_embedded_values_matches(self):
        res, _ = self.run_probe({("L1", A1): with_immutables(BASE, 99)}, [A1])
        self.assertEqual(res["verdict"], "MATCH")
        self.assertEqual(res["addresses"][0]["sameAs"], "Profile")

    def test_one_changed_byte_outside_the_mask_is_other_code(self):
        b = bytearray(with_immutables(BASE, 1)); b[10] ^= 1
        res, _ = self.run_probe({("L1", A1): bytes(b)}, [A1])
        self.assertEqual(res["verdict"], "DIFFERENT")
        self.assertEqual(res["addresses"][0]["status"], "other-code")

    def test_a_changed_byte_inside_the_mask_is_still_the_same(self):
        b = bytearray(with_immutables(BASE, 1)); b[101] ^= 0xFF
        res, _ = self.run_probe({("L1", A1): bytes(b)}, [A1])
        self.assertEqual(res["verdict"], "MATCH")

    def test_same_code_on_the_wrong_chain_is_not_the_same(self):
        # the release's L1 contract, found only on L2, is not "the same as a contract of the release on L2"
        res, _ = self.run_probe({("L2", A1): with_immutables(BASE, 1)}, [A1])
        self.assertEqual(res["addresses"][0]["status"], "other-code")

    def test_no_code_anywhere(self):
        res, _ = self.run_probe({}, [A1])
        self.assertEqual(res["verdict"], "DIFFERENT")
        self.assertEqual(res["addresses"][0]["status"], "no-code")
        self.assertEqual(res["noCode"], 1)

    def test_mixed_is_different_and_counts_add_up(self):
        t = {("L1", A1): with_immutables(BASE, 7), ("L1", A2): b"\x60\x00", ("L2", A3): with_immutables(BASE[::-1], 3)}
        res, _ = self.run_probe(t, [A1, A2, A3, A4])
        self.assertEqual(res["verdict"], "DIFFERENT")
        self.assertEqual((res["sameCode"], res["otherCode"], res["noCode"], res["checked"]), (2, 1, 1, 4))

    def test_all_chains_failing_is_an_error_never_a_match(self):
        res, _ = self.run_probe({("L1", A1): with_immutables(BASE, 1)}, [A1], fail=("L1", "L2"))
        self.assertEqual(res["verdict"], "ERROR")
        self.assertEqual(res["addresses"][0]["status"], "unreadable")

    def test_one_chain_failing_without_a_find_is_an_error(self):
        # no code was found on the chain that answered, and the other one did not answer: cannot call it "no code"
        res, _ = self.run_probe({}, [A1], fail=("L2",))
        self.assertEqual(res["verdict"], "ERROR")

    def test_one_chain_failing_with_a_find_still_answers(self):
        res, _ = self.run_probe({("L1", A1): with_immutables(BASE, 1)}, [A1], fail=("L2",))
        self.assertEqual(res["verdict"], "MATCH")

    def test_no_addresses_is_not_available(self):
        res, ch = self.run_probe({}, [])
        self.assertEqual(res["verdict"], "NOT_AVAILABLE")
        self.assertEqual(ch.calls, [])

    def test_bad_addresses_are_refused_before_any_request(self):
        for bad in ["0x12", "nothex" * 7, "0x" + "zz" * 20, 5, None, "0x" + "11" * 21]:
            saved = cc.rpc
            cc.rpc = FakeChain({})
            try:
                with self.assertRaises(P.Invalid):
                    P.probe(REF, [A1, bad])
                self.assertEqual(cc.rpc.calls, [])
            finally:
                cc.rpc = saved

    def test_too_many_addresses(self):
        many = [f"0x{i:040x}" for i in range(P.MAX_ADDRESSES + 1)]
        with self.assertRaises(P.Invalid):
            P.probe(REF, many)

    def test_duplicates_and_case_are_collapsed(self):
        res, ch = self.run_probe({("L1", A1): with_immutables(BASE, 1)}, [A1, A1.upper().replace("0X", "0x"), A1])
        self.assertEqual(res["checked"], 1)
        self.assertEqual(len([c for c in ch.calls if c[0] == "L1"]), 1)

    def test_a_pin_that_does_not_fit_the_code_is_skipped_not_a_crash(self):
        bad = {"address": "0x" + "ab" * 20, "basis": "published",
               "code": {"maskedHash": "0x" + "00" * 32, "mask": [[5000, 32]], "evidence": "observed-only"}}
        ref = {"chains": {"L1": {}}, "contracts": {"L1": {"X": bad}}}
        res, _ = self.run_probe({("L1", A1): BASE}, [A1], ref=ref)
        self.assertEqual(res["addresses"][0]["status"], "other-code")

    def test_only_code_is_ever_read(self):
        _, ch = self.run_probe({("L1", A1): BASE}, [A1])
        self.assertTrue(all(m == "eth_getCode" for _, m, _a in ch.calls))


if __name__ == "__main__":
    unittest.main(verbosity=1)
