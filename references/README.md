# references

Reference data: contract addresses, code hashes and file hashes. These are facts about public chains
and public builds, released under the same license as the rest of the repository.

- `testnet/reference_testnet_97cd13f3.contracts.json`: contract reference (format v1) for the CAW
  testnet set of upstream commit `97cd13f3`.
- `testnet/recompile_result_20261113.json`: the result of the independent recompile that the code
  pins of that reference rely on.

Who may publish a reference, and how a second independent build is required first, is not settled.
- `testnet/fingerprint_upstream-master-97cd13f3.clean-build.json`: address fingerprint (see `../formats/address-fingerprint.md`) of a clean build of the upstream repository's `master` at commit `97cd13f3` (nothing added; dependencies as the lock file pins them; `VITE_NETWORK_ID=1` only). That commit is the tip of `master`, not a tagged release. Made on 2026-11-13; the address set equals the one in the bundle a node served the same day.
- `releases.json`: the release registry (see `../formats/releases.md`). It has one entry for now: the upstream repository's `master` at `97cd13f3` (testnet), with its address fingerprint and contract reference and no file manifest.
