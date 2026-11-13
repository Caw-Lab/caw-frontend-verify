# verify

Part of [caw-frontend-verify](../README.md). Run the commands below from this folder.

Runs the three checks for one site against the releases in a [release registry](../formats/releases.md)
and **states the facts side by side**. It does not rank releases and does not say which one to trust.

```sh
python3 verify_site.py --site https://example.org --releases ../references/releases.json
python3 verify_site.py --dir ./build --releases ../references/releases.json --skip-chain
python3 verify_site.py --site https://example.org --releases releases.json --release my-release --json
python3 verify_site_test.py     # 18 scenarios; the chain check is skipped in the tests
```

For each release it reports:

| about | check | what is stated |
|---|---|---|
| this site | `frontend-check` (only when the release publishes a file manifest) | whether the site's files match the release's list |
| this site | `bridge` | whether the site's entry script names the release's contract addresses, and no others |
| this site (only with `--with-address-probe`) | `contract-check/site_address_probe.py` | for the addresses the site names that the release does not list: is there contract code on the chains, and is it the same code as one of the release's contracts |
| the release itself (only with `--with-release-check`) | `contract-check` | whether the contracts in the release's reference are consistent on the chains, and how their code was checked |

By default no chain is read: the check is the site's files (when the release has a file manifest) and the
addresses the site's main script names, and takes a few seconds. The address can be given without `https://`
(`verify_site.py cawnest.com`); an explicit `http://` is not changed.

The probe is about the site: a site that names other contracts gets a different answer. It only reads
(`eth_getCode`) and never decides "matched"; it says what is there, not what a contract does or whether a node
uses it. The last line is about the release, not about the site, so it is the same for every site (it takes minutes
and reads the chains about 170 times); ask for it with `--with-release-check`. `--skip-chain` stops either of them.

The tools are run as separate programs and their `--json` results are read; nothing is imported from
them. A tool that fails or cannot be read is reported as such and never counts as a match.

Exit code: 0 at least one release matched on every check that ran (and the contracts the site names
matched), 1 none did, 2 invalid input (the registry is refused, for example when it lists no releases,
repeats an id, or names a file that is missing or outside its directory), 3 no release matched and a
check could not be completed.

A match means consistent with that release's published files; it is not a guarantee of safety. Which
release to trust is the reader's decision.

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.

## Several sites at once

`make_status.py --sites sites.txt --releases releases.json --out status.json [--skip-chain]` checks every site in
`sites.txt` (one https address per line; `#` comments) and writes the [status file](../formats/status.md) that
[`../web/`](../web/) shows. A site that cannot be checked is recorded as such. An empty or repeating sites file is
refused.

## Just type an address

```sh
python3 verify_site.py your-node.example                # https:// can be left out; the bundled registry is used
python3 serve_local.py                                  # a page with a box for the address, opens in the browser
```

`serve_local.py` serves the page of [`../web/`](../web/) on `127.0.0.1` only. When an address is typed in, it runs
`verify_site.py` on this computer and shows the result; nothing is published. It is a small server that makes
network requests on request, so it defends itself:

- listens on `127.0.0.1` only; answers only requests whose `Host` is its own address, and refuses any other `Origin`
  (a web page elsewhere cannot use it);
- every API call needs a token made at start-up and handed only to the page it serves;
- one check at a time; the address is `https://` (added when left out) without credentials; loopback, private and link-local
  addresses are refused unless `--allow-private` is given (then `http://localhost` also works);
- serves only the four files of the page, with a strict content security policy.

Limits, stated plainly: the address is resolved once to be checked and again by the check, so a name that the typist
controls could change in between; the server protects against accidental and page-driven requests, not against a
person who types a hostile name into their own computer. `serve_local_test.py` (18 tests) starts a real server on a
free port with a fake check function and tries the refusals.
