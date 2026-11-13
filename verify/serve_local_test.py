#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Tests for serve_local.py: a real server on a free loopback port, with a fake check function."""
import http.client
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve_local as S  # noqa: E402

RESULT = {"site": "https://a.example", "releases": []}


class Base(unittest.TestCase):
    runner = staticmethod(lambda site, skip: dict(RESULT, site=site))
    allow_private = False

    @classmethod
    def setUpClass(cls):
        cls.calls = []

        def run(site, skip):
            cls.calls.append((site, skip))
            return cls.runner(site, skip)

        cls.srv, cls.app = S.make_server(0, run, cls.allow_private)
        cls.port = cls.app.port
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()
        cls.info = cls.req("GET", "/api/info")[1]
        cls.token = cls.info["token"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    @classmethod
    def req(cls, method, path, body=None, headers=None, host=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{cls.port}"}
        h.update(headers or {})
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        c.close()
        if raw:
            return r.status, payload, r
        try:
            return r.status, json.loads(payload), r
        except ValueError:
            return r.status, payload, r

    def auth(self, extra=None):
        h = {"X-Token": self.token}
        h.update(extra or {})
        return h

    def wait(self, jid):
        for _ in range(100):
            s, j, _ = self.req("GET", f"/api/job?id={jid}", headers=self.auth())
            if j.get("state") != "running":
                return j
            time.sleep(0.05)
        self.fail("job did not finish")


class TestNormalize(unittest.TestCase):
    def ok(self, u):
        return S.normalize_site(u)

    def bad(self, u, allow_private=False):
        with self.assertRaises(S.BadSite):
            S.normalize_site(u, allow_private)

    def test_https_names_become_origins(self):
        self.assertEqual(self.ok("https://1.1.1.1/anything?x=1#y"), "https://1.1.1.1")
        self.assertEqual(self.ok("  https://1.1.1.1:8443  "), "https://1.1.1.1:8443")

    def test_refused(self):
        for u in ["", None, 5, "   ", "ftp://1.1.1.1", "http://1.1.1.1", "https://", "https://user:pw@1.1.1.1", "user:pw@1.1.1.1",
                  "javascript:alert(1)", "1.1.1.1:notaport", "1.1.1.1:99999", "example.org:abc", "10.0.0.1", "192.168.1.1", "[::1]", "localhost", "localhost:3000",
                  "https://a b.example", "https://10.0.0.1", "https://192.168.1.1", "https://169.254.169.254",
                  "https://[::1]", "https://0.0.0.0", "https://[fe80::1]", "https://100.64.0.1", "x" * 400]:
            self.bad(u)

    def test_a_missing_scheme_means_https(self):
        self.assertEqual(S.normalize_site("1.1.1.1"), "https://1.1.1.1")
        self.assertEqual(S.normalize_site(" 1.1.1.1:8443/path?x=1 "), "https://1.1.1.1:8443")
        self.assertEqual(S.normalize_site("HTTPS://1.1.1.1"), "https://1.1.1.1")
        # an explicit http:// is not quietly upgraded: it is refused
        self.bad("http://1.1.1.1")

    def test_localhost_needs_the_switch(self):
        for u in ["http://localhost:3000/x", "https://localhost", "http://127.0.0.1:4001", "https://127.0.0.1", "https://[::1]"]:
            self.bad(u)
            self.assertTrue(S.normalize_site(u, True).startswith("http"))
        self.assertEqual(S.normalize_site("http://localhost:3000/x", True), "http://localhost:3000")
        self.assertEqual(S.normalize_site("http://127.0.0.1:4001", True), "http://127.0.0.1:4001")

    def test_private_needs_the_switch(self):
        self.assertEqual(S.normalize_site("https://10.0.0.1", True), "https://10.0.0.1")
        self.bad("https://10.0.0.1", False)


class TestServer(Base):
    def test_page_files_are_served_with_security_headers(self):
        for path, ctype in [("/", "text/html"), ("/render.js", "text/javascript"), ("/app.js", "text/javascript"), ("/style.css", "text/css")]:
            s, body, r = self.req("GET", path, raw=True)
            self.assertEqual(s, 200, path)
            self.assertTrue(r.getheader("Content-Type").startswith(ctype))
            self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.getheader("Cache-Control"), "no-store")

    def test_nothing_else_is_served(self):
        for path in ["/sample-status.json", "/README.md", "/../verify_site.py", "/test/render_test.js", "/%2e%2e/serve_local.py", "/status.json"]:
            self.assertEqual(self.req("GET", path)[0], 404, path)

    def test_wrong_host_is_refused(self):
        for h in ["evil.example", "evil.example:%d" % self.port, "127.0.0.1", "127.0.0.1:1", "localhost"]:
            self.assertEqual(self.req("GET", "/api/info", host=h)[0], 403, h)
            self.assertEqual(self.req("GET", "/", host=h)[0], 403, h)

    def test_foreign_origin_is_refused_everywhere(self):
        for o in ["https://evil.example", "http://evil.example", "null", "http://127.0.0.1:1", "http://localhost"]:
            self.assertEqual(self.req("GET", "/api/info", headers={"Origin": o})[0], 403, o)
            self.assertEqual(self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth({"Origin": o}))[0], 403, o)
        before = len(self.calls)
        self.assertEqual(len(self.calls), before)

    def test_own_origin_is_accepted(self):
        o = f"http://127.0.0.1:{self.port}"
        self.assertEqual(self.req("GET", "/api/info", headers={"Origin": o})[0], 200)

    def test_token_is_required_and_exact(self):
        for h in [{}, {"X-Token": ""}, {"X-Token": self.token + "x"}, {"X-Token": self.token[:-1]}, {"X-Token": "a" * 40}]:
            self.assertEqual(self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, h)[0], 403, h)
            self.assertEqual(self.req("GET", "/api/job?id=abc", headers=h)[0], 403, h)

    def test_a_check_runs_and_the_result_comes_back(self):
        s, j, _ = self.req("POST", "/api/check", {"site": "https://1.1.1.1/path", "skipChain": True}, self.auth())
        self.assertEqual(s, 202)
        out = self.wait(j["job"])
        self.assertEqual(out["state"], "done")
        self.assertEqual(out["result"]["site"], "https://1.1.1.1")
        self.assertEqual(self.calls[-1], ("https://1.1.1.1", True))

    def test_bad_requests(self):
        before = len(self.calls)
        cases = [
            ({"site": "http://1.1.1.1"}, 400), ({"site": "https://10.0.0.1"}, 400), ({"site": 5}, 400), ({}, 400),
            ([], 400), ("x", 400),
        ]
        for body, code in cases:
            self.assertEqual(self.req("POST", "/api/check", body, self.auth())[0], code, body)
        self.assertEqual(self.req("POST", "/api/check", b"{not json", self.auth())[0], 400)
        self.assertEqual(self.req("POST", "/api/check", b"x" * 5000, self.auth())[0], 413)
        self.assertEqual(self.req("POST", "/api/check", b"{}", self.auth({"Content-Type": "text/plain"}))[0], 415)
        self.assertEqual(self.req("POST", "/api/other", {}, self.auth())[0], 404)
        self.assertEqual(len(self.calls), before, "a refused request must not start a check")

    def test_other_methods_are_refused(self):
        for m in ["PUT", "DELETE", "PATCH"]:
            self.assertEqual(self.req(m, "/api/check", {}, self.auth())[0], 405)

    def test_unknown_job(self):
        self.assertEqual(self.req("GET", "/api/job?id=nope", headers=self.auth())[0], 404)
        self.assertEqual(self.req("GET", "/api/job", headers=self.auth())[0], 404)


class TestOneAtATime(Base):
    gate = threading.Event()

    @staticmethod
    def runner(site, skip):
        TestOneAtATime.gate.wait(5)
        return dict(RESULT, site=site)

    def test_second_check_is_refused_while_one_runs(self):
        s, j, _ = self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth())
        self.assertEqual(s, 202)
        self.assertEqual(self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth())[0], 429)
        self.assertEqual(self.req("GET", f"/api/job?id={j['job']}", headers=self.auth())[1]["state"], "running")
        self.gate.set()
        self.assertEqual(self.wait(j["job"])["state"], "done")
        self.assertEqual(self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth())[0], 202)


class TestFailures(Base):
    @staticmethod
    def runner(site, skip):
        raise RuntimeError("boom " + "x" * 500)

    def test_a_failed_check_is_an_error_never_a_result(self):
        s, j, _ = self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth())
        out = self.wait(j["job"])
        self.assertEqual(out["state"], "error")
        self.assertNotIn("result", out)
        self.assertLessEqual(len(out["error"]), 200)
        # and the server accepts a new check afterwards
        self.assertEqual(self.req("POST", "/api/check", {"site": "https://1.1.1.1"}, self.auth())[0], 202)
        time.sleep(0.2)


class TestListening(unittest.TestCase):
    def test_binds_loopback_only(self):
        srv, app = S.make_server(0)
        try:
            self.assertEqual(srv.server_address[0], "127.0.0.1")
        finally:
            srv.server_close()

    def test_source_has_no_wildcard_bind_and_no_shell(self):
        with open(os.path.join(os.path.dirname(S.__file__), "serve_local.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('"0.0.0.0"', src)
        self.assertNotIn('("", ', src)
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)
        self.assertNotIn("Access-Control-Allow", src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
