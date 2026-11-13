# SPDX-License-Identifier: MIT
# Copyright (c) 2026 zinsanjp and contributors
"""Search the history of one contract source for the compiler settings that reproduce the code on a chain.

  python3 recompile_older_compiler_search.py WORKDIR

WORKDIR is a scratch directory that must already hold: `src/` (a git clone of the repository, with its
dependencies installed under solidity/node_modules), `reference.json` (a contract reference) and
`chain_check_prototype.py` (a copy of the checker). It downloads solc 0.8.22 from the official site and
verifies its sha256 against the published list. A one-off provenance search, not part of the normal checks.
"""
import hashlib, importlib.util, itertools, json, os, subprocess, sys, urllib.request
if len(sys.argv) != 2:
    sys.exit(__doc__)
D = sys.argv[1]
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "caw-frontend-verify/0"}), timeout=300).read()
lst = json.loads(get("https://binaries.soliditylang.org/linux-amd64/list.json"))
b = next(x for x in lst["builds"] if x["version"] == "0.8.22")
data = get("https://binaries.soliditylang.org/linux-amd64/" + b["path"])
assert "0x" + hashlib.sha256(data).hexdigest() == b["sha256"]
open(D + "/solc-0.8.22", "wb").write(data); os.chmod(D + "/solc-0.8.22", 0o755)
print("solc 0.8.22 sha256 verified:", b["sha256"], b["longVersion"])
spec = importlib.util.spec_from_file_location("cc", D + "/chain_check_prototype.py"); cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
ref = json.load(open(D + "/reference.json"))
addr = ref["contracts"]["L1"]["MintableCaw"]["address"]
chain = bytes.fromhex(cc.rpc("L1", "eth_getCode", [addr, "latest"])["result"][2:])
SOL = D + "/src/solidity"
revs = subprocess.run(["git", "-C", D + "/src", "log", "--format=%h", "--", "solidity/contracts/MintableCaw.sol"], capture_output=True, text=True).stdout.split()
def strip(b): return b[:-(int.from_bytes(b[-2:], "big") + 2)]
found = []
for rev in revs:
    src = subprocess.run(["git", "-C", D + "/src", "show", f"{rev}:solidity/contracts/MintableCaw.sol"], capture_output=True).stdout
    path = f"{SOL}/contracts/_hist_{rev}.sol"; open(path, "wb").write(src)
    for via, opt, evm in itertools.product((False, True), (None, 1, 200, 1000000), (None, "paris", "shanghai", "london", "cancun")):
        st = {"outputSelection": {"*": {"*": ["evm.deployedBytecode.object"]}}}
        if via: st["viaIR"] = True
        st["optimizer"] = {"enabled": opt is not None, **({"runs": opt} if opt else {})}
        if evm: st["evmVersion"] = evm
        inp = {"language": "Solidity", "sources": {f"contracts/_hist_{rev}.sol": {"urls": [f"contracts/_hist_{rev}.sol"]}}, "settings": st}
        p = subprocess.run([D + "/solc-0.8.22", "--standard-json", "--base-path", SOL, "--include-path", SOL + "/node_modules", "--allow-paths", SOL], input=json.dumps(inp), capture_output=True, text=True)
        try: res = json.loads(p.stdout)
        except Exception: continue
        if any(e.get("severity") == "error" for e in res.get("errors", [])): continue
        code = bytes.fromhex(res["contracts"][f"contracts/_hist_{rev}.sol"]["MintableCaw"]["evm"]["deployedBytecode"]["object"])
        if len(code) == len(chain):
            tag = "IDENTICAL" if code == chain else ("identical-except-metadata" if strip(code) == strip(chain) else "same-length-but-differs")
            print(rev, f"viaIR={via} runs={opt} evm={evm}", tag)
            if tag != "same-length-but-differs": found.append((rev, via, opt, evm, tag))
    os.remove(path)
print("FOUND:", found)
