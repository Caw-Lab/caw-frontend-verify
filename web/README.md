# web

Part of [caw-frontend-verify](../README.md). A static page that **shows** the results of the checks. It
does not run any check itself: a browser cannot read the files of an arbitrary site unless that site sends
CORS headers, and today's nodes do not. The checks run elsewhere (`verify/verify_site.py`, later a
scheduled job) and write a [status file](../formats/status.md); the page reads it.

Files: `index.html`, `render.js` (turns the JSON into a view model and words the facts, English and
Japanese; no DOM), `app.js` (the page), `style.css`. No libraries, no fonts, nothing loaded from another
address. The page can be put on any static host.

## Use

- **Type an address (easiest):** run `python3 verify/serve_local.py` (from the `caw-frontend-verify` folder) and the
  page opens with a box for a site address. Type the address (`https://` can be left out), press Check, and the result appears. See
  [`../verify/README.md`](../verify/README.md) for what the local server does and how it protects itself. The box
  exists only when the page is served by that local server; anywhere else the page only shows results it is given.

- Or put a `status.json` next to `index.html`; the page loads it. Or open a result file, or paste the JSON
  printed by `verify_site.py --json`.
- `sample-status.json` is a real result from 2026-11-13 (two nodes, one release). It is a sample, not a
  published status.
- Preview locally: `python3 -m http.server 8099 --bind 127.0.0.1` in a folder holding the four files and a
  `status.json`, then open `http://127.0.0.1:8099`.

## What it states

For each site and each release: the facts about the **site** (do its files match the release's list? does
its main script name the release's contract addresses, and no others? what is on the chains at the addresses
it names that the release does not list?) and, only when it was run, the facts about the **release itself**
(are the contracts in its reference consistent on the chains? the same for every site); both are shown only when the result contains them. It does not rank
releases and does not say which one to trust. Colors are green (matches), amber (differs), grey (no
conclusion, not checked); there is no red, and every state is also written in words.

## Safety of the page

- Strict content security policy (`default-src 'none'`, scripts and styles only from the page's own
  directory, connections only to itself). A real host should also send it as an HTTP header, with
  `Strict-Transport-Security`.
- Data is put on the page with `textContent` only; no HTML is built from data, nothing is evaluated, no
  link or source is set from data. The tests check this by reading the code.
- Requests: `status.json` and, in local mode only, the local server's `/api/` paths; never redirects, never credentials,
  never another address. The tests check this by reading the code.

## Tests

`node --test test/render_test.js` (Node 22): 29 tests on the view model, the wording (English and Japanese,
and that a failure never reads like the success sentence), long or hostile input, and static checks of the
page (content security policy, no external resources, no dangerous APIs).

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.
