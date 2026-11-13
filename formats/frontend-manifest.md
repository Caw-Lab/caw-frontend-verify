# Frontend manifest (draft)

A JSON file listing every file of a frontend build with its SHA-256.

```json
{
  "version": 1,
  "clientVersion": "string, names the build",
  "builtAt": "ISO 8601 time",
  "files": { "assets/app-1a2b3c.js": "sha256-<64 hex digits>", "index.html": "sha256-<64 hex digits>" }
}
```

- Paths are relative to the site root. The hash is `sha256-` followed by the lowercase hex digest.
- A manifest whose `files` is empty (an empty object or array) is not a valid reference, and a checker
  refuses it. Paths must be relative, without `..`, a scheme, a backslash or control characters; hashes
  must be `sha256-` plus 64 hex digits (either case); more than 5000 files is refused.
- Files that are not listed (for example the manifest itself, and service-worker files that change
  with every build) are not covered by a check; a result must say so.

The format is read by `frontend-check`. Still open: the exact exclusions and the way a reference is
published.

---
License: MIT. Copyright (c) 2026 zinsanjp and contributors.
