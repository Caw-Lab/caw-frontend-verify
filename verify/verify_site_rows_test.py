#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Tests for how verify_site.judge combines the tools' results (fake run_tool, no network)."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vs", os.path.join(HERE, "verify_site.py"))
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

REL = [{"id": "r1", "publisher": {"name": "p", "kind": "upstream"}, "network": "testnet",
        "source": {"repo": "a/b", "commit": "c" * 40, "tagged": False}, "lineage": None,
        "_manifest": None, "_fp": "fp.json", "_ref": "ref.json"}]
U = [{"address": "0x" + "aa" * 20, "label": None}, {"address": "0x" + "bb" * 20, "label": None}]


class Fake:
    def __init__(self, bridge, probe=None, chain=None):
        self.bridge, self.probe, self.chain, self.calls = bridge, probe, chain, []

    def __call__(self, name, args):
        self.calls.append((name, args))
        r = {"bridge": self.bridge, "probe": self.probe, "chain": self.chain}[name]
        if r is None:
            raise AssertionError(f"{name} must not run here")
        return r


class T(unittest.TestCase):
    def judge(self, fake, **kw):
        saved = vs.run_tool
        vs.run_tool = fake
        try:
            return vs.judge(REL, "https://x.example", None, kw.pop("skip_chain", False), **kw)[0]
        finally:
            vs.run_tool = saved

    def names(self, fake):
        return [c[0] for c in fake.calls]

    def test_unlisted_addresses_are_sent_to_the_probe_with_the_reference(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U, "missing": []}, {"verdict": "DIFFERENT", "checked": 2})
        r = self.judge(f, with_address_probe=True)
        probe = [c for c in f.calls if c[0] == "probe"][0][1]
        self.assertEqual(probe, ["--reference", "ref.json", "--address", U[0]["address"], "--address", U[1]["address"]])
        self.assertEqual(r["facts"]["namedOnChain"]["verdict"], "DIFFERENT")

    def test_no_chain_is_read_by_default_and_the_row_is_absent(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U})
        r = self.judge(f)
        self.assertEqual(self.names(f), ["bridge"])
        self.assertNotIn("namedOnChain", r["facts"])
        self.assertNotIn("Names on chain", vs.render("https://x.example", [r]))

    def test_an_address_without_scheme_gets_https(self):
        self.assertEqual(vs.with_scheme("cawnest.com"), "https://cawnest.com")
        self.assertEqual(vs.with_scheme("  cawnest.com:8443/x "), "https://cawnest.com:8443/x")
        self.assertEqual(vs.with_scheme("https://cawnest.com"), "https://cawnest.com")
        self.assertEqual(vs.with_scheme("http://x.example"), "http://x.example")  # an explicit scheme is never changed (the tools refuse http)

    def test_the_release_itself_is_not_checked_by_default(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U}, {"verdict": "DIFFERENT"})
        r = self.judge(f)
        self.assertNotIn("chain", self.names(f))
        self.assertEqual(r["facts"]["contractsOnChain"]["verdict"], "SKIPPED")

    def test_the_release_check_runs_once_when_asked(self):
        f = Fake({"verdict": "MATCH", "unexpected": []}, None, {"verdict": "PASS"})
        r = self.judge(f, with_release_check=True)
        self.assertEqual(self.names(f).count("chain"), 1)
        self.assertEqual(r["facts"]["contractsOnChain"]["verdict"], "PASS")
        self.assertTrue(r["matched"])

    def test_nothing_unlisted_means_no_probe(self):
        f = Fake({"verdict": "MATCH", "unexpected": []})
        r = self.judge(f, with_address_probe=True)
        self.assertNotIn("probe", self.names(f))
        self.assertEqual(r["facts"]["namedOnChain"]["verdict"], "NOT_AVAILABLE")
        self.assertTrue(r["matched"])

    def test_skip_chain_reads_no_chain(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U})
        r = self.judge(f, skip_chain=True, with_address_probe=True)
        self.assertEqual(self.names(f), ["bridge"])
        self.assertEqual(r["facts"]["namedOnChain"]["verdict"], "SKIPPED")
        self.assertEqual(r["facts"]["contractsOnChain"]["verdict"], "SKIPPED")

    def test_an_unreadable_site_is_not_probed(self):
        f = Fake({"verdict": "UNREADABLE", "reason": "x"})
        r = self.judge(f, with_address_probe=True)
        self.assertNotIn("probe", self.names(f))
        self.assertEqual(r["facts"]["namedOnChain"]["verdict"], "NOT_AVAILABLE")
        self.assertFalse(r["matched"])

    def test_the_probe_never_decides_matched(self):
        # even if the probe says the unlisted addresses carry the release's own code, a site that names other addresses is not a match
        f = Fake({"verdict": "DIFFERENT", "unexpected": U}, {"verdict": "MATCH", "checked": 2})
        self.assertFalse(self.judge(f, with_address_probe=True)["matched"])
        # and a failing probe cannot turn a match into a non-match
        f = Fake({"verdict": "MATCH", "unexpected": []}, {"verdict": "ERROR"})
        self.assertTrue(self.judge(f, with_address_probe=True)["matched"])

    def test_a_probe_error_does_not_make_a_clear_difference_incomplete(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U}, {"verdict": "ERROR", "reason": "rpc"})
        r = self.judge(f, with_address_probe=True)
        self.assertFalse(r["incomplete"])
        self.assertEqual(r["facts"]["namedOnChain"]["verdict"], "ERROR")

    def test_very_many_addresses_are_capped_and_counted(self):
        many = [{"address": f"0x{i:040x}", "label": None} for i in range(vs.MAX_PROBE + 7)]
        f = Fake({"verdict": "DIFFERENT", "unexpected": many}, {"verdict": "DIFFERENT", "checked": vs.MAX_PROBE})
        r = self.judge(f, with_address_probe=True)
        sent = [c for c in f.calls if c[0] == "probe"][0][1]
        self.assertEqual(sent.count("--address"), vs.MAX_PROBE)
        self.assertEqual(r["facts"]["namedOnChain"]["notChecked"], 7)

    def test_text_report_shows_the_new_row_and_hides_the_skipped_release_row(self):
        f = Fake({"verdict": "DIFFERENT", "unexpected": U, "missing": []},
                 {"verdict": "DIFFERENT", "checked": 2, "sameCode": 0, "otherCode": 2, "noCode": 0})
        text = vs.render("https://x.example", [self.judge(f, with_address_probe=True)])
        self.assertIn("Names on chain", text)
        self.assertIn("2 other code", text)
        self.assertNotIn("about the release itself", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
