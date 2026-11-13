# frontend-check

Part of [caw-frontend-verify](../README.md). Run the commands below from this folder.

Compares the files a site serves with a **frontend manifest** (a SHA-256 per file path). It answers:
are the files this site serves the files the manifest lists? It does not look at contracts (see
`contract-check` and `bridge`), and it says nothing about the node's backend or configuration.

Python 3 and the standard library only (a prototype; the logic is small and meant to be ported to
JavaScript for a browser page).

## Usage

```sh
python3 frontend_check.py check --site https://example.org --manifest manifest.json
python3 frontend_check.py check --site https://example.org \
    --manifest https://raw.githubusercontent.com/<owner>/<repo>/<ref>/manifests/latest.json
python3 frontend_check.py check --dir ./build --manifest manifest.json      # a local directory
python3 frontend_check_negative_test.py     # 35 scenarios; network only to 127.0.0.1
```

Options: `--index-from-root` (read `index.html` from `/`, for hosts that redirect `/index.html` to `/`),
`--concurrency` (default 4, at most 8), `--max-file-mb` (32), `--max-total-mb` (512), `--timeout` (20 s per
request), `--deadline` (900 s for the whole run), `--json`.

## Result

| result | exit code | meaning |
|---|---|---|
| `MATCH` | 0 | every file the manifest lists was read and matches |
| `DIFFERENT` | 1 | at least one file differs or is missing |
| `INVALID` | 2 | the manifest or the arguments are unusable (nothing was checked) |
| `INCOMPLETE` | 3 | nothing differs, but some files could not be read: no conclusion, never a pass |

A missing file (HTTP 404) counts as a difference. On a site that answers `200` with the app for any
unknown path, a missing file shows up as a mismatch.

## What it does when reading a site

- https only (http for localhost); no credentials in the address or the manifest URL;
- **does not follow redirects**: the site must answer at the address given; a redirected file is
  reported as unreadable;
- reads each file as a stream and hashes it, never holding a whole file in memory;
- limits: a size per file, a **total byte budget** for the run, a timeout per request, an overall
  deadline, and a cap on parallel requests;
- a manifest that lists no files is refused, as are unsafe paths (`..`, absolute, a URL, a backslash),
  malformed hashes, an unsupported version, and more than 5000 files.

## Reading the result

`MATCH` means the listed files are what they should be at the time of the check. Files the manifest does
not list are **not covered**: for example the manifest file itself and service-worker files, which change
with every build, if the manifest leaves them out. The report says so every time. A site can still behave
differently depending on who asks, and a match says nothing about its backend or configuration.

Which manifest to compare with is a choice: a manifest says who built the files and from what only if its
publisher says so (see [`../formats/frontend-manifest.md`](../formats/frontend-manifest.md)).

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.
