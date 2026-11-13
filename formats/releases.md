# Release registry (v1)

A JSON file listing the releases a site can be compared with. Each entry says **who published it**,
**what it is based on**, and **which reference files belong to it**. It does not rank releases: which
one to trust is the reader's choice.

```json
{
  "schemaVersion": 1,
  "kind": "caw-releases",
  "releases": [
    {
      "id": "upstream-master-97cd13f3-testnet",
      "publisher": { "name": "GilgameshCaw (upstream repository)", "kind": "upstream" },
      "network": "testnet",
      "source": { "repo": "GilgameshCaw/Caw", "commit": "<40 hex digits>", "tagged": false },
      "title": "(optional) a name a reader understands, e.g. \"Upstream V2 contract list, as of 2026-09-21\"", "titleJa": "(optional) the same in Japanese",
      "sourceDesc": "(optional) where the code comes from, concretely, e.g. \"Upstream master branch (Org/Repo, commit abc1234 as of 2026-01-01)\"", "sourceDescJa": "(optional) the same in Japanese",
      "lineage": { "basedOn": null, "note": "what this release is, in plain words", "noteJa": "(optional) the same in Japanese" },
      "frontend": { "addressFingerprint": "testnet/fingerprint_….json", "manifest": null },
      "contracts": { "reference": "testnet/reference_….contracts.json" },
      "notes": ["anything a reader should know"]
    }
  ]
}
```

- `id`: letters, digits, `.`, `_`, `-`; unique in the file.
- `publisher.kind`: `upstream` (the repository the code comes from) or `lab` (a downstream group that
  builds its own frontend). A downstream release says what it is based on in `lineage.basedOn`: the
  upstream commit, the upstream pull requests it includes, and a description of its own changes.
- `source`: the repository and commit the release was built from; `tagged` says whether that commit is a
  tagged release.
- `frontend.addressFingerprint` (required): an [address fingerprint](address-fingerprint.md) of the
  release's frontend build. `frontend.manifest` (optional, `null` when absent): a
  [frontend manifest](frontend-manifest.md) of the release's files. A release whose builds differ per
  operator (settings baked into the files) has a fingerprint but no manifest.
- `contracts.reference` (required): a [contract reference](contract-reference.md). Two releases may point
  at the same one (a downstream frontend that uses the upstream deployment).
- File paths are relative to the registry file, stay inside its directory, and must exist.

A registry that lists no releases, repeats an id, names a file that is missing or outside its directory,
or has a release without the required parts is refused (`INVALID`).

---
License: MIT. Copyright (c) 2026 zinsanjp and contributors.
