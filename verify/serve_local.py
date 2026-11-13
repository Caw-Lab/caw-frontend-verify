#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""A local page with a box for a site address.

  serve_local.py [--port 8099] [--allow-private] [--no-open]

Serves the page of ../web on 127.0.0.1 only and, when an address is typed into it, runs verify_site.py
on this computer and shows the result. Nothing is published and nothing leaves this computer except the
checks themselves (requests to the typed site and to public RPC endpoints).

Because the server runs checks that make network requests, it defends itself:
  - it listens on 127.0.0.1 only and answers only requests whose Host header is this address
    (a web page cannot reach it through a name that points here);
  - every API call needs a secret token that is made at start-up and given only to the page it serves;
    a request that carries an Origin other than this server's own is refused;
  - one check runs at a time; an address must be https (typed without it, https:// is added; http://localhost only with
    --allow-private), without credentials,
    and must not be a private, loopback or link-local address unless --allow-private is given;
  - only the four files of the page are served.
"""
import argparse
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
VERIFY = os.path.join(HERE, "verify_site.py")
RELEASES = os.path.join(ROOT, "references", "releases.json")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/render.js": ("render.js", "text/javascript; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_BODY = 4096
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


class BadSite(Exception):
    pass


def normalize_site(url, allow_private=False):
    """An origin (https://host[:port]) from what was typed, or BadSite."""
    if not isinstance(url, str) or len(url) > 300:
        raise BadSite("give a site address")
    text = url.strip()
    if "://" not in text:
        text = "https://" + text  # 'cawnest.com' means https://cawnest.com
    try:
        u = urllib.parse.urlsplit(text)
        host, port_number = u.hostname, u.port
    except ValueError:
        raise BadSite("that is not an address")
    if u.username or u.password:
        raise BadSite("an address has no credentials")
    if not host:
        raise BadSite("give an address such as https://example.org")
    local_name = host in ("localhost", "127.0.0.1", "::1")
    if u.scheme != "https" and not (u.scheme == "http" and local_name and allow_private):
        raise BadSite("only https:// addresses can be checked (http://localhost only with --allow-private)")
    try:
        ip = ipaddress.ip_address(host)
        addrs = [ip]
    except ValueError:
        if not HOST_RE.match(host):
            raise BadSite("that is not a host name")
        try:
            addrs = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, port_number or 443, proto=socket.IPPROTO_TCP)]
        except OSError:
            raise BadSite("that name cannot be resolved")
    if not allow_private and (local_name or any(not a.is_global for a in addrs)):
        raise BadSite("that address is private, loopback or link-local; it is refused (--allow-private lifts this)")
    port = f":{port_number}" if port_number else ""
    shown = f"[{host}]" if ":" in host else host
    return f"{u.scheme}://{shown}{port}"


def default_runner(site, skip_chain):
    cmd = [sys.executable, "-I", VERIFY, "--site", site, "--releases", RELEASES, "--json"] + (["--skip-chain"] if skip_chain else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    try:
        res = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError("the check produced no readable result")
    if "releases" not in res:
        raise RuntimeError(str(res.get("reason", "the check was refused"))[:200])
    return res


class App:
    def __init__(self, port, runner=default_runner, allow_private=False):
        self.port, self.runner, self.allow_private = port, runner, allow_private
        self.token = secrets.token_urlsafe(24)
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.lock = threading.Lock()
        self.jobs, self.running = {}, None

    def start_job(self, site, skip_chain):
        with self.lock:
            if self.running:
                return None
            jid = secrets.token_hex(8)
            self.jobs[jid] = {"state": "running", "started": time.time()}
            self.running = jid
            for old in list(self.jobs)[:-5]:
                self.jobs.pop(old, None)
        threading.Thread(target=self._run, args=(jid, site, skip_chain), daemon=True).start()
        return jid

    def _run(self, jid, site, skip_chain):
        try:
            res = self.runner(site, skip_chain)
            out = {"state": "done", "result": res}
        except Exception as e:  # a failed check is reported, never shown as a match
            out = {"state": "error", "error": (str(e) or type(e).__name__)[:200]}
        with self.lock:
            out["started"] = self.jobs.get(jid, {}).get("started", time.time())
            self.jobs[jid] = out
            self.running = None


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = "caw-verify-local"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                         "Content-Security-Policy": CSP, "Cross-Origin-Resource-Policy": "same-origin",
                         "X-Frame-Options": "DENY"}.items():
                self.send_header(k, v)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode())

        def _guard(self):
            """Host check for everything; Origin check when present."""
            if self.headers.get("Host", "") not in app.hosts:
                self._json(403, {"error": "forbidden host"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in app.origins:
                self._json(403, {"error": "forbidden origin"})
                return False
            return True

        def _token_ok(self):
            if not secrets.compare_digest(self.headers.get("X-Token", ""), app.token):
                self._json(403, {"error": "missing or wrong token"})
                return False
            return True

        def do_GET(self):
            if not self._guard():
                return
            u = urllib.parse.urlsplit(self.path)
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                try:
                    with open(os.path.join(WEB, name), "rb") as f:
                        self._send(200, f.read(), ctype)
                except OSError:
                    self._json(404, {"error": "not found"})
                return
            if u.path == "/api/info":
                self._json(200, {"local": True, "token": app.token})
                return
            if u.path == "/api/job":
                if not self._token_ok():
                    return
                jid = urllib.parse.parse_qs(u.query).get("id", [""])[0]
                with app.lock:
                    job = dict(app.jobs.get(jid, {}))
                if not job:
                    self._json(404, {"error": "no such job"})
                    return
                job["elapsed"] = int(time.time() - job.get("started", time.time()))
                job.pop("started", None)
                self._json(200, job)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if urllib.parse.urlsplit(self.path).path != "/api/check":
                self._json(404, {"error": "not found"})
                return
            if not self._token_ok():
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                self._json(415, {"error": "send JSON"})
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._json(413, {"error": "body too large"})
                return
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                site = normalize_site(body.get("site"), app.allow_private) if isinstance(body, dict) else None
                if site is None:
                    raise BadSite("send an object with a site")
            except BadSite as e:
                self._json(400, {"error": str(e)})
                return
            except Exception:
                self._json(400, {"error": "that is not a valid request"})
                return
            jid = app.start_job(site, bool(body.get("skipChain")))
            if jid is None:
                self._json(429, {"error": "a check is already running"})
                return
            self._json(202, {"job": jid})

        def _no(self):
            self._json(405, {"error": "method not allowed"})

        do_PUT = do_DELETE = do_PATCH = _no

    return H


def make_server(port, runner=default_runner, allow_private=False):
    # the port is needed for the Host check, so bind first and read it back
    probe = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    real = probe.server_address[1]
    probe.server_close()
    app = App(real, runner, allow_private)
    srv = ThreadingHTTPServer(("127.0.0.1", real), make_handler(app))
    srv.daemon_threads = True
    return srv, app


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--allow-private", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)
    try:
        srv, app = make_server(a.port, allow_private=a.allow_private)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{a.port}: {e.strerror or e}  (try --port 0 for any free port)")
        return 2
    url = f"http://127.0.0.1:{app.port}/"
    print(f"open {url} and type the address of a site. Stop with Ctrl+C. Listening on 127.0.0.1 only.")
    if not a.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
