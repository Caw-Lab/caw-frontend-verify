# Status file (v1)

What `verify/make_status.py` writes and `web/` shows: the results of checking several sites.

```json
{
  "schemaVersion": 1,
  "kind": "caw-verify-status",
  "generatedAt": "2026-11-13T04:04:39Z",
  "sites": [
    { "site": "https://example.org", "result": { "site": "…", "releases": [ … ] } },
    { "site": "https://other.example", "error": "the check timed out" }
  ]
}
```

- `result` is the JSON `verify_site.py --json` prints: one entry per release, with the facts about the site
  and about the release (see `verify/README.md`).
- A site whose check could not be run or read carries an `error` instead of a `result`. It is shown as
  "could not be checked", never as a match.
- A status file lists at least one site; the page also accepts a single `verify_site.py --json` result, or
  a list of them.

The page treats the file as untrusted data: it shows text only, cuts long strings and long lists, and
treats `matched` as true only when it is exactly `true`.

---
License: MIT. Copyright (c) 2026 zinsanjp and contributors.
