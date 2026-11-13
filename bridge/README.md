# bridge

Part of [caw-frontend-verify](../README.md). Run the commands below from this folder.

Answers one question: **which contracts does this frontend point at?** It reads the files a site
serves, extracts the contract addresses compiled into the application's entry script, and compares them
with an [address fingerprint](../formats/address-fingerprint.md) of a reference build. It does not check
that the files are unchanged (`frontend-check`), and it does not talk to a chain (`contract-check`).
A contract reference, if given, only adds names to the report.

Python 3 and the standard library only (a prototype; the logic is small and meant to be ported to
JavaScript for a browser page).

## Usage

```sh
# make a fingerprint from a build directory or a site
python3 bridge_check.py fingerprint --dir ./build --name my-release --out fingerprint.json

# check a site (or --dir) against it; the contract reference is optional and only labels addresses
python3 bridge_check.py check --site https://example.org --fingerprint fingerprint.json \
    --reference ../references/testnet/reference_testnet_97cd13f3.contracts.json

python3 bridge_negative_test.py     # 26 scenarios, no network except 127.0.0.1
```

Result and exit code: `MATCH` 0, `DIFFERENT` 1, `INVALID` 2 (bad input), `UNREADABLE` 3 (the site could
not be read; never a pass).

## What it does when reading a site

- https only (http for localhost); no credentials in the address;
- does not follow redirects (the site must answer at the address given);
- reads `index.html`, the first module script (the entry script) and the preloaded module chunks, with a
  size limit and a timeout; a script path that leaves the site is refused.
- a script path that answers with an HTML page (a site that serves its index page for every unknown path) is
  `UNREADABLE`, not a script without addresses.

## Reading the result

`MATCH`: every expected address is present and the entry script names no other contract address. That
says which contracts the entry script names. It does **not** rule out a frontend that hides or computes
other addresses at run time (a test documents this limit), that has been changed in other ways, or whose
node backend reads a different deployment. For that, compare the files themselves (`frontend-check`).

`DIFFERENT` lists what is missing and what is unexpected, with names where a contract reference knows
the address. A frontend copied and pointed at its own contracts lacks the reference's addresses.

The fingerprint in `../references/testnet/` was made from a clean build of upstream `master` at commit
`97cd13f3` (not a tagged release). A node that serves that build, with its own settings, names the same
addresses.

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.
