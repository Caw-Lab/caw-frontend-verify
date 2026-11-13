#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Which contracts does a frontend point at?

Reads the files a site serves (or a local directory), extracts the contract addresses compiled into
the application's entry script, and compares them with an *address fingerprint*: the set of addresses
found in the entry script of a reference build. It does not check that the files are unchanged (that
is the job of frontend-check), and it does not talk to any chain (that is contract-check).

  bridge_check.py fingerprint (--site URL | --dir DIR) --name NAME --out fingerprint.json
  bridge_check.py check       (--site URL | --dir DIR) --fingerprint fingerprint.json [--reference contract-reference.json]

Result and exit code: MATCH 0, DIFFERENT 1, INVALID 2 (bad input), UNREADABLE 3 (site not readable).
A match means "the entry script contains exactly the reference's addresses". It does not rule out a
frontend that hides or computes other addresses, or that has been changed in other ways.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
HEX40 = re.compile(r"^0x[0-9a-fA-F]{40}$")
MAX_INDEX = 2 * 1024 * 1024
MAX_SCRIPT = 16 * 1024 * 1024
TIMEOUT = 20

# Addresses that appear in almost any bundle and say nothing about which deployment is meant.
GENERIC_EXACT = {
    "0x000000000000000000000000000000000000dead": "burn address",
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": "native-token placeholder",
    "0xca11bde05977b3631167028862be2a173976ca11": "Multicall3",
}


class Unreadable(Exception):
    pass


class Invalid(Exception):
    pass


def generic_label(addr):
    a = addr.lower()
    if a in GENERIC_EXACT:
        return GENERIC_EXACT[a]
    if a.startswith("0x" + "0" * 36):
        return "low address (zero, precompile)"
    if re.match(r"^0x42" + "0" * 36 + r"[0-9a-f]{2}$", a):
        return "OP-stack predeploy"
    return None


def extract(text):
    """All 20-byte hex addresses in a text, lowercased, without the generic ones."""
    found = {m.lower() for m in ADDR_RE.findall(text)}
    return {a for a in found if generic_label(a) is None}


# ------------------------------------------------------------------ sources
class DirSource:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.name = f"directory {root}"

    def get(self, path, limit):
        p = os.path.realpath(os.path.join(self.root, path.lstrip("/")))
        if not (p == self.root or p.startswith(self.root + os.sep)):
            raise Unreadable("a path points outside the site directory")
        try:
            with open(p, "rb") as f:
                data = f.read(limit + 1)
        except OSError:
            raise Unreadable(f"cannot read {path}")
        if len(data) > limit:
            raise Unreadable(f"{path} is larger than {limit} bytes")
        return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class HttpSource:
    def __init__(self, url):
        u = urllib.parse.urlsplit(url.strip())
        local = u.hostname in ("localhost", "127.0.0.1", "::1")
        if u.scheme != "https" and not (u.scheme == "http" and local):
            raise Invalid("only https:// sites can be read (http:// is allowed for localhost only)")
        if not u.hostname or u.username or u.password:
            raise Invalid("a site address has a host name and no credentials")
        host = u.hostname if ":" not in u.hostname else f"[{u.hostname}]"
        self.base = f"{u.scheme}://{host}" + (f":{u.port}" if u.port else "")
        self.name = self.base
        self._opener = urllib.request.build_opener(_NoRedirect)

    def get(self, path, limit):
        url = f"{self.base}/{path.lstrip('/')}"
        req = urllib.request.Request(url, headers={"user-agent": "caw-frontend-verify-bridge/0"})
        try:
            with self._opener.open(req, timeout=TIMEOUT) as r:
                declared = r.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise Unreadable(f"{path} declares more than {limit} bytes")
                data = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise Unreadable(f"{path} redirected (enter the address the site answers at)")
            raise Unreadable(f"{path} answered HTTP {e.code}")
        except Unreadable:
            raise
        except Exception as e:
            raise Unreadable(f"{path}: {type(e).__name__}")
        if len(data) > limit:
            raise Unreadable(f"{path} is larger than {limit} bytes")
        return data


def make_source(site, directory):
    if (site is None) == (directory is None):
        raise Invalid("give either --site or --dir")
    return HttpSource(site) if site else DirSource(directory)


# ------------------------------------------------------------------ the page
def _attr(tag, name):
    m = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I)
    return None if not m else (m.group(1) or m.group(2) or m.group(3) or "")


def page_scripts(html):
    """(entry script path, [preloaded module paths], number of external scripts)."""
    entry, pre, external = None, [], 0

    def local(p):
        nonlocal external
        if p is None:
            return None
        if "://" in p or p.startswith("//"):
            external += 1
            return None
        segments = [x for x in p.split("?")[0].split("#")[0].split("/") if x not in ("", ".")]
        if ".." in segments:
            raise Unreadable("a script path points outside the site")
        return "/".join(segments)

    for m in re.finditer(r"<script\b[^>]*>", html, re.I):
        tag = m.group(0)
        if (_attr(tag, "type") or "").lower() == "module" and _attr(tag, "src") is not None:
            p = local(_attr(tag, "src"))
            if p and entry is None:
                entry = p
    for m in re.finditer(r"<link\b[^>]*>", html, re.I):
        tag = m.group(0)
        if (_attr(tag, "rel") or "").lower() == "modulepreload":
            p = local(_attr(tag, "href"))
            if p and p.endswith(".js"):
                pre.append(p)
    return entry, pre, external


def scan(source):
    """Read the page and its entry script; return what was found."""
    html = source.get("index.html", MAX_INDEX).decode("utf-8", errors="replace")
    entry, pre, external = page_scripts(html)
    if not entry:
        raise Unreadable("index.html has no module entry script")
    entry_text = source.get(entry, MAX_SCRIPT).decode("utf-8", errors="replace")
    all_addrs = set(extract(entry_text))
    read = [entry]
    for p in dict.fromkeys(pre):
        if p == entry:
            continue
        try:
            all_addrs |= extract(source.get(p, MAX_SCRIPT).decode("utf-8", errors="replace"))
            read.append(p)
        except Unreadable:
            pass  # a preload that cannot be read only weakens the presence check
    return {"entry": entry, "entryAddresses": extract(entry_text), "allAddresses": all_addrs,
            "filesRead": read, "externalScripts": external}


# ------------------------------------------------------------------ fingerprint
def make_fingerprint(source, name, description=""):
    found = scan(source)
    if not found["entryAddresses"]:
        raise Invalid("the entry script contains no contract address; nothing to fingerprint")
    return {
        "license": "MIT",
        "copyright": "Copyright (c) 2026 zinsanjp and contributors",
        "schemaVersion": 1,
        "kind": "caw-frontend-address-fingerprint",
        "name": name,
        "createdAt": datetime.date.today().isoformat(),
        "derivedFrom": {"description": description, "entryFile": found["entry"]},
        "addresses": sorted(found["entryAddresses"]),
    }


def validate_fingerprint(fp):
    p = []
    if not isinstance(fp, dict):
        return ["fingerprint is not an object"]
    if fp.get("schemaVersion") != 1:
        p.append(f"unsupported schemaVersion {fp.get('schemaVersion')!r}")
    if fp.get("kind") != "caw-frontend-address-fingerprint":
        p.append("kind must be 'caw-frontend-address-fingerprint'")
    a = fp.get("addresses")
    if not isinstance(a, list) or not a:
        p.append("addresses missing or empty (a fingerprint that checks nothing is refused)")
    else:
        bad = [x for x in a if not (isinstance(x, str) and HEX40.match(x))]
        if bad:
            p.append(f"addresses: not a 20-byte hex address: {bad[0]!r}")
        low = [x.lower() for x in a if isinstance(x, str)]
        if len(set(low)) != len(low):
            p.append("addresses: duplicates")
        gen = [x for x in low if HEX40.match(x) and generic_label(x)]
        if gen:
            p.append(f"addresses: {gen[0]} is a generic address and says nothing about a deployment")
    return p


def labels_from_reference(ref):
    out = {}
    if isinstance(ref, dict):
        for ch, cs in (ref.get("contracts") or {}).items():
            for nm, e in (cs or {}).items():
                try:
                    out.setdefault(e["address"].lower(), f"{ch}.{nm}")
                except Exception:
                    pass
    return out


def check(source, fp, reference=None):
    problems = validate_fingerprint(fp)
    if problems:
        raise Invalid("; ".join(problems))
    found = scan(source)
    required = {a.lower() for a in fp["addresses"]}
    missing = sorted(required - found["allAddresses"])
    unexpected = sorted(found["entryAddresses"] - required)
    labels = labels_from_reference(reference)
    present = sorted(required & found["allAddresses"])
    return {
        "verdict": "MATCH" if not missing and not unexpected else "DIFFERENT",
        "site": source.name, "entry": found["entry"], "fingerprint": fp.get("name"),
        "required": len(required), "present": len(present),
        "missing": [(a, labels.get(a)) for a in missing],
        "unexpected": [(a, labels.get(a)) for a in unexpected],
        "recognized": sorted(labels[a] for a in present if a in labels),
        "externalScripts": found["externalScripts"], "filesRead": found["filesRead"],
    }


def render(r):
    lines = [f"site:        {r['site']}", f"fingerprint: {r['fingerprint']}",
             f"entry:       {r['entry']}  ({len(r['filesRead'])} script(s) read, {r['externalScripts']} external not read)",
             f"addresses:   {r['present']} of {r['required']} expected are present"]
    if r["recognized"]:
        lines.append(f"recognized in the contract reference: {', '.join(r['recognized'])}")
    for a, lb in r["missing"]:
        lines.append(f"  MISSING     {a}" + (f"  ({lb})" if lb else ""))
    for a, lb in r["unexpected"]:
        lines.append(f"  UNEXPECTED  {a}" + (f"  ({lb})" if lb else "") + "  (in the entry script, not in the fingerprint)")
    lines.append(f"VERDICT: {r['verdict']}")
    if r["verdict"] == "MATCH":
        lines.append("note: this says which contracts the entry script names; it does not show the files are unchanged.")
    return "\n".join(lines)


CODES = {"MATCH": 0, "DIFFERENT": 1, "INVALID": 2, "UNREADABLE": 3}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fingerprint", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("--site")
        sp.add_argument("--dir")
    sub.choices["fingerprint"].add_argument("--name", required=True)
    sub.choices["fingerprint"].add_argument("--description", default="")
    sub.choices["fingerprint"].add_argument("--out", required=True)
    sub.choices["check"].add_argument("--fingerprint", required=True)
    sub.choices["check"].add_argument("--reference")
    sub.choices["check"].add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    as_json = getattr(args, "json", False)

    def fail(verdict, reason):
        if as_json:
            print(json.dumps({"tool": "bridge", "verdict": verdict, "reason": reason}))
        else:
            print(f"VERDICT: {verdict}: {reason}")
        return CODES[verdict]

    try:
        src = make_source(args.site, args.dir)
        if args.cmd == "fingerprint":
            fp = make_fingerprint(src, args.name, args.description)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(fp, f, indent=1)
                f.write("\n")
            print(f"wrote {args.out}: {len(fp['addresses'])} addresses from {fp['derivedFrom']['entryFile']}")
            return 0
        fp = json.load(open(args.fingerprint, encoding="utf-8"))
        ref = json.load(open(args.reference, encoding="utf-8")) if args.reference else None
        r = check(src, fp, ref)
        if as_json:
            print(json.dumps({"tool": "bridge", "verdict": r["verdict"], "site": r["site"], "fingerprint": r["fingerprint"],
                              "required": r["required"], "present": r["present"], "entry": r["entry"],
                              "missing": [{"address": a, "label": l} for a, l in r["missing"]],
                              "unexpected": [{"address": a, "label": l} for a, l in r["unexpected"]],
                              "recognized": r["recognized"], "externalScripts": r["externalScripts"]}))
        else:
            print(render(r))
        return CODES[r["verdict"]]
    except Invalid as e:
        return fail("INVALID", str(e))
    except Unreadable as e:
        return fail("UNREADABLE", str(e))
    except (OSError, ValueError) as e:
        return fail("INVALID", f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
