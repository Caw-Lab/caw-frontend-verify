#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Compare one site with the releases of a release registry and state the facts.

  verify_site.py URL                       (the simplest form: the bundled release registry is used)
  verify_site.py (--site URL | --dir DIR) [--releases releases.json] [--release ID ...] [--skip-chain] [--with-address-probe] [--with-release-check] [--json]

For each release it runs the checks the release supports and reports, side by side:
  - the frontend files   (frontend-check, when the release publishes a file manifest)
  - the contracts the frontend names   (bridge, against the release's address fingerprint)
  - the contracts on the chains        (contract-check, against the release's contract reference)
The tools are run as separate programs and their JSON results are read; nothing is imported from them.
The report does not rank releases and does not say which one to trust.

Exit code: 0 at least one release matched on every check that ran, 1 none did, 2 invalid input
(registry, arguments), 3 no release matched and some check could not be completed.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = {
    "bridge": os.path.join(ROOT, "bridge", "bridge_check.py"),
    "frontend": os.path.join(ROOT, "frontend-check", "frontend_check.py"),
    "chain": os.path.join(ROOT, "contract-check", "chain_check_prototype.py"),
    "probe": os.path.join(ROOT, "contract-check", "site_address_probe.py"),
}
TIMEOUTS = {"bridge": 180, "frontend": 1000, "chain": 400, "probe": 300}
MAX_PROBE = 60  # addresses sent to the on-chain probe; more are counted, not checked
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
DEFAULT_RELEASES = os.path.join(ROOT, "references", "releases.json")


class Invalid(Exception):
    pass


# ------------------------------------------------------------------ registry
def _inside(base, rel):
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        return None
    p = os.path.realpath(os.path.join(base, rel))
    return p if (p.startswith(base + os.sep) and os.path.isfile(p)) else None


def load_registry(path):
    try:
        with open(path, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError) as e:
        raise Invalid(f"cannot read the registry: {type(e).__name__}")
    base = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    problems = []
    if not isinstance(reg, dict) or reg.get("schemaVersion") != 1 or reg.get("kind") != "caw-releases":
        raise Invalid("registry: schemaVersion must be 1 and kind 'caw-releases'")
    rels = reg.get("releases")
    if not isinstance(rels, list) or not rels:
        raise Invalid("registry lists no releases (a registry that checks nothing is refused)")
    seen = set()
    for i, r in enumerate(rels):
        tag = f"release {i}"
        if not isinstance(r, dict):
            problems.append(f"{tag}: not an object")
            continue
        rid = r.get("id")
        if not (isinstance(rid, str) and ID_RE.match(rid)):
            problems.append(f"{tag}: bad id")
            continue
        tag = f"release {rid}"
        if rid in seen:
            problems.append(f"{tag}: duplicate id")
        seen.add(rid)
        if not (isinstance(r.get("publisher"), dict) and r["publisher"].get("name") and r["publisher"].get("kind") in ("upstream", "lab")):
            problems.append(f"{tag}: publisher needs a name and kind 'upstream' or 'lab'")
        src = r.get("source")
        if not (isinstance(src, dict) and src.get("repo") and re.match(r"^[0-9a-f]{40}$", str(src.get("commit", "")))):
            problems.append(f"{tag}: source needs a repo and a 40-digit commit")
        fe, ct = r.get("frontend") or {}, r.get("contracts") or {}
        r["_fp"] = _inside(base, fe.get("addressFingerprint"))
        if r["_fp"] is None:
            problems.append(f"{tag}: frontend.addressFingerprint is missing, outside the registry directory, or not a file")
        r["_manifest"] = None
        if fe.get("manifest") is not None:
            r["_manifest"] = _inside(base, fe["manifest"])
            if r["_manifest"] is None:
                problems.append(f"{tag}: frontend.manifest is outside the registry directory or not a file")
        r["_ref"] = _inside(base, ct.get("reference"))
        if r["_ref"] is None:
            problems.append(f"{tag}: contracts.reference is missing, outside the registry directory, or not a file")
    if problems:
        raise Invalid("; ".join(problems[:6]) + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else ""))
    return rels


# ------------------------------------------------------------------ running the tools
def run_tool(name, args):
    """Run a tool with --json. Returns its result dict, or one with verdict ERROR."""
    try:
        p = subprocess.run([sys.executable, "-I", TOOLS[name]] + args + ["--json"], capture_output=True, text=True,
                           timeout=TIMEOUTS[name], cwd=os.path.dirname(TOOLS[name]))
    except subprocess.TimeoutExpired:
        return {"tool": name, "verdict": "ERROR", "reason": f"timed out after {TIMEOUTS[name]} s"}
    except OSError as e:
        return {"tool": name, "verdict": "ERROR", "reason": f"cannot start: {type(e).__name__}"}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        tail = (p.stderr or "").strip().splitlines()[-1][:160] if (p.stderr or "").strip() else ""
        return {"tool": name, "verdict": "ERROR", "reason": f"no JSON result (exit {p.returncode})" + (f": {tail}" if tail else "")}


def site_args(site, directory):
    return ["--site", site] if site else ["--dir", directory]


POSITIVE = {"frontend": "MATCH", "bridge": "MATCH", "chain": "PASS"}


def with_scheme(url):
    """'cawnest.com' -> 'https://cawnest.com'; an address that names a scheme is left as it is."""
    u = url.strip()
    return u if "://" in u else "https://" + u


def judge(releases, site, directory, skip_chain, with_release_check=False, with_address_probe=False):
    chain_cache = {}
    out = []
    for r in releases:
        facts = {}
        if r["_manifest"]:
            facts["frontendFiles"] = run_tool("frontend", ["check"] + site_args(site, directory) + ["--manifest", r["_manifest"]])
        else:
            facts["frontendFiles"] = {"verdict": "NOT_AVAILABLE", "reason": "this release publishes no file manifest"}
        facts["contractsNamed"] = run_tool("bridge", ["check"] + site_args(site, directory) + ["--fingerprint", r["_fp"], "--reference", r["_ref"]])

        # On request: what is on the chains at the addresses the site names that the list does not have.
        if with_address_probe:
            named = facts["contractsNamed"]
            extra = [e["address"] for e in named.get("unexpected", []) if isinstance(e, dict) and isinstance(e.get("address"), str)]
            if skip_chain:
                facts["namedOnChain"] = {"verdict": "SKIPPED", "reason": "chain check skipped (--skip-chain)"}
            elif named.get("verdict") not in ("MATCH", "DIFFERENT"):
                facts["namedOnChain"] = {"verdict": "NOT_AVAILABLE", "reason": "the site's addresses could not be read"}
            elif not extra:
                facts["namedOnChain"] = {"verdict": "NOT_AVAILABLE", "reason": "the site names no address outside the release"}
            else:
                args = ["--reference", r["_ref"]]
                for a in extra[:MAX_PROBE]:
                    args += ["--address", a]
                res = run_tool("probe", args)
                if len(extra) > MAX_PROBE:
                    res["notChecked"] = len(extra) - MAX_PROBE
                facts["namedOnChain"] = res

        # The release's own reference, checked on the chains. The same for every site, so it is run only on request.
        if skip_chain:
            facts["contractsOnChain"] = {"verdict": "SKIPPED", "reason": "chain check skipped (--skip-chain)"}
        elif not with_release_check:
            facts["contractsOnChain"] = {"verdict": "SKIPPED", "reason": "the release itself is not re-checked each time (--with-release-check)"}
        else:
            if r["_ref"] not in chain_cache:
                chain_cache[r["_ref"]] = run_tool("chain", [r["_ref"]])
            facts["contractsOnChain"] = chain_cache[r["_ref"]]

        # namedOnChain is information about the site; it never decides "matched".
        ran = [(k, v) for k, v in facts.items() if k != "namedOnChain" and v["verdict"] not in ("NOT_AVAILABLE", "SKIPPED")]
        names = {"frontendFiles": "frontend", "contractsNamed": "bridge", "contractsOnChain": "chain"}
        positive = [v["verdict"] == POSITIVE[names[k]] for k, v in ran]
        incomplete = any(v["verdict"] in ("ERROR", "INCOMPLETE", "UNREADABLE") for _, v in ran)
        matched = bool(ran) and all(positive) and facts["contractsNamed"]["verdict"] == "MATCH"
        out.append({"id": r["id"], "title": r.get("title"), "titleJa": r.get("titleJa"), "sourceDesc": r.get("sourceDesc"), "sourceDescJa": r.get("sourceDescJa"), "publisher": r["publisher"], "network": r.get("network"), "source": r["source"],
                    "lineage": r.get("lineage"), "facts": facts, "matched": matched, "incomplete": incomplete and not matched})
    return out


# ------------------------------------------------------------------ report
def sentence(key, v):
    verdict = v["verdict"]
    if key == "frontendFiles":
        if verdict == "MATCH":
            return f"the files match this release's list ({v.get('match')} of {v.get('listed')})"
        if verdict == "DIFFERENT":
            return f"the files differ from this release's list ({v.get('mismatch')} mismatch, {v.get('missing')} missing)"
        if verdict == "INCOMPLETE":
            return f"no conclusion: {v.get('error')} file(s) could not be read"
    if key == "contractsNamed":
        if verdict == "MATCH":
            return f"the entry script names this release's contract addresses ({v.get('present')} of {v.get('required')}) and no others"
        if verdict == "DIFFERENT":
            return (f"the entry script names other contracts: {len(v.get('missing', []))} of this release's addresses are absent, "
                    f"{len(v.get('unexpected', []))} unlisted addresses are present")
    if key == "namedOnChain":
        if verdict == "MATCH":
            return f"all {v.get('checked')} address(es) carry the same code as a contract of this release (at other addresses)"
        if verdict == "DIFFERENT":
            return (f"of {v.get('checked')} address(es) the release does not list: {v.get('sameCode', 0)} same code as the release's, "
                    f"{v.get('otherCode', 0)} other code, {v.get('noCode', 0)} no code on the chains")
    if key == "contractsOnChain":
        if verdict == "PASS":
            ev = v.get("codeEvidence") or {}
            built = ev.get("recompile-identical", 0) + ev.get("recompile-except-metadata", 0)
            return (f"the contracts in this release's reference are consistent on the chains ({sum(v.get('summary', {}).values())} checks; "
                    f"{built} contract(s) rebuilt from source and identical to the chain code)")
        if verdict == "FAIL":
            return f"the chains differ from this release's reference ({len(v.get('flagged', []))} check(s) flagged)"
    reason = v.get("reason")
    return f"{verdict.lower().replace('_', ' ')}" + (f": {reason}" if reason else "")


LABELS = {"frontendFiles": "Site files", "contractsNamed": "Site names", "namedOnChain": "Names on chain",
          "contractsOnChain": "Release on chain"}


def render(site_name, results):
    lines = [f"Site: {site_name}", ""]
    for r in results:
        src = r["source"]
        lines.append(f"Release {r['id']}")
        lines.append(f"  published by {r['publisher']['name']} ({r['publisher']['kind']}); {src['repo']} @ {src['commit'][:8]}"
                     f"{'' if src.get('tagged') else ' (not a tagged release)'}; network: {r['network']}")
        if r.get("lineage") and r["lineage"].get("note"):
            lines.append(f"  based on: {r['lineage']['note']}")
        lines.append("  about this site:")
        for key in ("frontendFiles", "contractsNamed", "namedOnChain"):
            if key in r["facts"]:
                lines.append(f"    {LABELS[key]:<17} {sentence(key, r['facts'][key])}")
        if r["facts"]["contractsOnChain"]["verdict"] != "SKIPPED":
            lines.append("  about the release itself (the same for every site):")
            lines.append(f"    {LABELS['contractsOnChain']:<17} {sentence('contractsOnChain', r['facts']['contractsOnChain'])}")
        status = "MATCHES on every check that ran" if r["matched"] else ("INCOMPLETE" if r["incomplete"] else "does not match")
        lines.append(f"  -> {status}")
        lines.append("")
    lines.append("This report states what the site's files and the chains show. Which release to trust is your decision.")
    lines.append("A match means consistent with that release's published files; it is not a guarantee of safety.")
    return "\n".join(lines)


def exit_code(results):
    if any(r["matched"] for r in results):
        return 0
    return 3 if any(r["incomplete"] for r in results) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", nargs="?", help="the site to check (same as --site)")
    ap.add_argument("--site")
    ap.add_argument("--dir")
    ap.add_argument("--releases", default=DEFAULT_RELEASES, help="release registry (default: the bundled references/releases.json)")
    ap.add_argument("--release", action="append", default=[], help="only this release id (repeatable)")
    ap.add_argument("--skip-chain", action="store_true", help="do not read the chains at all (faster)")
    ap.add_argument("--with-address-probe", action="store_true",
                    help="also look up, on the chains, the addresses the site names that the release does not list")
    ap.add_argument("--with-release-check", action="store_true",
                    help="also check the release's own reference on the chains (the same for every site; takes minutes)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.url is not None:
            if a.site is not None:
                raise Invalid("give the site once: either the address or --site")
            a.site = a.url
        if a.site is not None:
            a.site = with_scheme(a.site)
        if (a.site is None) == (a.dir is None):
            raise Invalid("give either a site address (or --site) or --dir")
        rels = load_registry(a.releases)
        if a.release:
            unknown = [x for x in a.release if x not in {r["id"] for r in rels}]
            if unknown:
                raise Invalid(f"unknown release id: {unknown[0]}")
            rels = [r for r in rels if r["id"] in a.release]
    except Invalid as e:
        print(json.dumps({"verdict": "INVALID", "reason": str(e)}) if a.json else f"INVALID: {e}")
        return 2
    results = judge(rels, a.site, a.dir, a.skip_chain, a.with_release_check, a.with_address_probe)
    site_name = a.site or f"directory {a.dir}"
    if a.json:
        print(json.dumps({"site": site_name, "releases": results}, indent=1))
    else:
        print(render(site_name, results))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
