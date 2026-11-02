#!/usr/bin/env python3
"""Compare the `files` maps of build-manifest.json files from several builds.

usage: compare_manifests.py <results-dir>
  expects manifest-<id>.json, and optionally env-<id>.txt, deps-fe-<id>.txt,
  deps-client-<id>.txt for each build id. `builtAt` is ignored (it changes on
  every build); `clientVersion` is compared and reported.
Prints Markdown. Exit code is 0 even when builds differ: a difference is a
result, not a failure of this script.
"""
import json
import os
import re
import sys


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_lines(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return set(l.rstrip("\n") for l in f if l.strip())


def strip_hash(name):
    # assets/index-AbC123.js -> assets/index.js (best effort, for counting
    # how many *logical* files changed content vs only got another name)
    return re.sub(r"-[A-Za-z0-9_]{6,12}(\.[A-Za-z0-9.]+)$", r"\1", name)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    ids = sorted(
        m.group(1)
        for f in os.listdir(d)
        if (m := re.fullmatch(r"manifest-(.+)\.json", f))
    )
    if len(ids) < 2:
        print(f"Need at least two manifests in {d}, found {ids}")
        return 0

    man = {i: load(os.path.join(d, f"manifest-{i}.json")) for i in ids}
    print("# Reproducibility comparison\n")
    print("| build | clientVersion | files |")
    print("|---|---|---|")
    for i in ids:
        print(f"| {i} | `{man[i].get('clientVersion')}` | {len(man[i]['files'])} |")
    print()
    for i in ids:
        env = os.path.join(d, f"env-{i}.txt")
        if os.path.exists(env):
            print(f"- {i}: " + "; ".join(open(env, encoding="utf-8").read().split("\n")[:3]))
    print()

    print("| pair | identical `files` | only in first | only in second | same name, different content |")
    print("|---|---|---|---|---|")
    details = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            fa, fb = man[a]["files"], man[b]["files"]
            same = fa == fb
            only_a = sorted(set(fa) - set(fb))
            only_b = sorted(set(fb) - set(fa))
            diff = sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k])
            print(f"| {a} vs {b} | {'yes' if same else 'NO'} | {len(only_a)} | {len(only_b)} | {len(diff)} |")
            if not same:
                details.append((a, b, only_a, only_b, diff))
    print()

    for a, b, only_a, only_b, diff in details:
        print(f"## {a} vs {b}: differences\n")
        print(f"- names only in {a}: {len(only_a)} (first 10: {only_a[:10]})")
        print(f"- names only in {b}: {len(only_b)} (first 10: {only_b[:10]})")
        print(f"- same name, different content: {len(diff)} (first 10: {diff[:10]})")
        logical_a = {strip_hash(n) for n in only_a}
        logical_b = {strip_hash(n) for n in only_b}
        print(f"- logical names (hash part removed) that differ: {len(logical_a ^ logical_b)}")
        for kind in ("deps-fe", "deps-client"):
            sa = read_lines(os.path.join(d, f"{kind}-{a}.txt"))
            sb = read_lines(os.path.join(d, f"{kind}-{b}.txt"))
            if sa is None or sb is None:
                continue
            delta = sorted(sa ^ sb)
            print(f"- {kind} packages that differ between the two installs: {len(delta)} (first 15: {delta[:15]})")
        print()

    if not details:
        print("All builds produced identical `files`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
