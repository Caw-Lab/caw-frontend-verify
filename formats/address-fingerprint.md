# Frontend address fingerprint (v1)

The set of contract addresses compiled into the entry script of a reference frontend build. `bridge`
compares the entry script of a site with it.

```json
{
  "schemaVersion": 1,
  "kind": "caw-frontend-address-fingerprint",
  "name": "release or build the fingerprint belongs to",
  "createdAt": "2026-11-13",
  "derivedFrom": { "description": "how it was made", "entryFile": "assets/index-<hash>.js" },
  "addresses": ["0x…", "0x…"],
  "addressNotes": { "0x…": { "en": "what this address is", "ja": "the same in Japanese" } }
}
```

- `addresses`: every 20-byte hex address found in the entry script of the reference build, lowercase,
  without generic addresses (the zero address and other low addresses, the burn address, the
  native-token placeholder, Multicall3, OP-stack predeploys), which say nothing about a deployment.
- The list is taken from the build itself, so no names are needed (a minified bundle has none). Names
  are added at report time from a contract reference, when one is given.
- `addressNotes` (optional): short explanations of addresses a reader may see in a result, because they are
  in the list but missing from a site, or in a site but not in the list. The key is a lowercase address (it
  may be one that is not in `addresses`); `en` and `ja` are texts of 1 to 300 characters; at most 50 entries.
  A note is shown next to the address. It never changes a verdict.
- **Refused as INVALID:** a wrong `kind` or version, an empty list (a fingerprint that checks nothing),
  a malformed or duplicate address, a generic address, a malformed `addressNotes`.

## What a match means

The site's entry script names exactly these addresses: every one is present (in the entry script or a
preloaded chunk), and the entry script names no other contract address. A match does not show that the
files are unchanged, that the page does not build or fetch other addresses at run time, or what the
node's backend reads.

## How to make one

From a clean build of a release (a directory, or a served copy):
`python3 bridge_check.py fingerprint --dir <build-dir> --name <release> --out fingerprint.json`.
A fingerprint made from a node's own bundle is only as good as that node's build; mark it provisional.

---
License: MIT. Copyright (c) 2026 zinsanjp and contributors.
