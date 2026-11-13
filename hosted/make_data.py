#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Make src/data.json for the hosted service from the release registry.

  make_data.py [--check]

For every release of ../references/releases.json it takes what the contract check needs: the address
fingerprint, labels for the addresses (from the contract reference), and the facts a reader sees
(names, source). --check writes nothing and exits 1 when src/data.json is not what this would make.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "..", "references", "releases.json")
OUT = os.path.join(HERE, "src", "data.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def labels_from_reference(ref):
    out = {}
    for ch, cs in (ref.get("contracts") or {}).items():
        for nm, e in (cs or {}).items():
            if isinstance(e, dict) and isinstance(e.get("address"), str):
                out.setdefault(e["address"].lower(), f"{ch}.{nm}")
    return out


def build():
    reg = load(REGISTRY)
    base = os.path.dirname(os.path.abspath(REGISTRY))
    releases = []
    for r in reg["releases"]:
        fp = load(os.path.join(base, r["frontend"]["addressFingerprint"]))
        ref = load(os.path.join(base, r["contracts"]["reference"]))
        required = {a.lower() for a in fp["addresses"]}
        labels = {a: l for a, l in labels_from_reference(ref).items() if a in required}
        releases.append({
            "id": r["id"], "title": r.get("title"), "titleJa": r.get("titleJa"),
            "sourceDesc": r.get("sourceDesc"), "sourceDescJa": r.get("sourceDescJa"),
            "publisher": r["publisher"], "network": r.get("network"), "source": r["source"],
            "lineage": r.get("lineage"),
            "fingerprint": {"schemaVersion": fp["schemaVersion"], "kind": fp["kind"], "name": fp["name"],
                            "addresses": sorted(required)},
            "labels": dict(sorted(labels.items())),
        })
    return {"generatedFrom": "references/releases.json", "releases": releases}


def main(argv):
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        have = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else None
        if have != text:
            print("src/data.json is not up to date; run make_data.py")
            return 1
        print("src/data.json is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {OUT}: {len(json.loads(text)['releases'])} release(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
