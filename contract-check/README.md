# contract-check

Part of [caw-frontend-verify](../README.md). Run the commands below from this folder.

A small, read-only checker that compares the contracts a CAW deployment points at with a
**reference file**. It reads the chains through public JSON-RPC (`eth_chainId`, `eth_getCode`,
`eth_call`); it never signs or sends anything.

Status: prototype. Not affiliated with, or endorsed by, the CAW project. A passing check means
"consistent with the reference", not "safe".

## Also here: `site_address_probe.py`

`site_address_probe.py --reference REF.json --address 0x… [--address 0x…]` reads what is on the chains at
addresses a site names that a release does not list: is there contract code, and is it the same code (ignoring
the values a constructor embeds) as one of the release's contracts on that chain. `site_address_probe_test.py`
(15 tests) runs it against a fake chain. It reads code only.

## What it checks

For every contract listed in the reference file:

1. the chain id behind each RPC is the expected one;
2. the address has code, and the runtime code hashes to the pinned value (regions that differ per
   deployment — immutable values and linked library addresses — are zeroed first);
3. every linked library address found inside the code is the one the reference lists, and that
   library is pinned too;
4. the rules hold: a getter returns a given contract (`link`), the zero address (`zero`) or an
   integer (`value`); a LayerZero `peers(eid)` entry (`peer`); an endpoint `delegates(...)` entry
   (`delegate`).

A malformed reference is refused (`INVALID`) rather than passed: an empty rule list, a missing code
pin, a rule that names an unlisted contract, and so on. Result: `PASS`, `FAIL` or `INVALID`
(exit code 0, 1, 2). The format is described in [`../formats/contract-reference.md`](../formats/contract-reference.md).

## Usage

```sh
python3 chain_check_prototype.py ../references/testnet/reference_testnet_97cd13f3.contracts.json
python3 chain_check_negative_test.py ../references/testnet/reference_testnet_97cd13f3.contracts.json   # 34 broken-reference scenarios
```

Python 3 and the standard library only. The RPC endpoints per chain key (`L1`, `L2`, `L2b`) are set
at the top of `chain_check_prototype.py` (`RPC_URL`); replace them with your own if you prefer.

Making a reference (see the header of each script for details):

```sh
python3 make_contract_reference.py base.json                  # addresses from a fixed upstream commit + values read from the chain
python3 add_code_pins.py base.json pinned.json                # code pins, library links, evidence from Sourcify data
python3 recompile_independent.py <scratch-dir> pinned.json <commit>   # independent recompile (needs a checkout in <scratch-dir>/src)
python3 apply_recompile.py pinned.json recompile_result.json out.json
```

## Evidence behind a code pin

| evidence | meaning |
|---|---|
| `recompile-identical` | our own recompile (source at a fixed commit, npm dependencies checked against the lock file's sha512, official `solc` checked against the official sha256 list) equals the chain code, metadata included |
| `recompile-except-metadata` | equal except the trailing metadata (older compiler or different source text); conditions in `provenance.olderCompiler` |
| `sourcify-exact-match` / `sourcify-match` | Sourcify's recompiled code, compared with the chain code by this tool (Sourcify's verdict is not taken on trust) |
| `same-code-as:<chain.name>` | the same code as another listed contract, regions as for that contract |
| `observed-only` | pinned from the chain on the day the file was made; detects later change only |

## Provenance

This code was written from scratch, with the Python standard library only. Nothing was copied from
the upstream Verifier, from other pull requests, or from other projects. Inputs from others:

- Keccak-256 is implemented from the public Keccak specification and self-tested against known vectors.
- Contract names and getter names come from the MIT-licensed Solidity sources in
  `GilgameshCaw/Caw` (`solidity/contracts`); only the few names the rules need are used.
- Addresses come from `client/src/abi/deployments.ts` and `addresses.ts` of that repository at a
  fixed commit (data about public chains).
- Immutable and library-link positions, and recompiled code, were read from the Sourcify API
  (`sourcify.dev`) when a reference was made; no Sourcify code is used.
- The independent recompile used the official Solidity compiler (`binaries.soliditylang.org`) and the
  npm packages named in the contracts' `package-lock.json`, in a scratch directory only; none of it is
  included here.
- Default RPC endpoints are public ones (`publicnode.com`).

The reference files contain addresses and hashes, which are facts about public chains; they are
released under the same license.

## Limits

- One release (upstream commit `97cd13f3`) and one testnet set; mainnet is not covered. The checker
  hard-codes the three chain keys.
- Third-party contracts (LayerZero endpoint, swap router, WETH, SP1 verifier) are not recompiled; they
  rely on Sourcify's recompile.
- The check cannot tell whether the reference itself is the *right* deployment; it compares the chain
  with the reference. A consistent but malicious set of contracts listed in a reference would pass.
- Values pinned as `observed` / `external` fix the state of the day the file was made.

## License

MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors. Contributions are
accepted under the same license.
