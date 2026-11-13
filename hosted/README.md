# hosted

Part of [caw-frontend-verify](../README.md). A public service that checks, for any site, **which contract
addresses its main script names**, and compares them with a published build. It is the contract check of
[`bridge`](../bridge/README.md), ported to a Cloudflare Worker, behind the page of [`web`](../web/README.md).

It does **not** check the files of a site (there is no file fingerprint yet; the page says so), and it reads no
chain. A match means "the entry script names exactly the published addresses". It does not show that the files
are unchanged, and it says nothing about what a node's server side reads.

## What it does

`POST /api/check` with `{"site": "cawnest.com"}` (the `https://` can be left out) makes two requests to the site
(`index.html` and the entry script, a few more only if an address is still missing) and answers with the same JSON
that `verify/verify_site.py --json` gives for one release. The page of `../web` is served from the same place,
and shows a box for the address when it finds this service.

- `GET /api/info` answers `{"hosted": true}`; the page uses it to know where it is.
- Nothing about a checked site is stored by this code, and it writes no log. The platform keeps its own operational
  logs. A result is kept in memory (and in the platform's cache, where that works) for five minutes.

## What it refuses (before any request to the site)

Anyone can type an address, so the service is strict:

- Only a plain public **https host name**: no IP address (also not the disguised forms: `127.1`, `0x7f.1`,
  `2130706433`), no user name, no port other than 443, no `localhost`, `.local`, `.internal` and similar, no single
  label, no whitespace or control characters, nothing that starts with `/`, not the service's own name.
- The name is looked up (DNS over HTTPS) and refused unless **every** address it points at is public; private,
  loopback, link-local, shared, reserved, multicast, unique-local, mapped-private, NAT64 and 6to4 addresses are not.
  A name that changes its answer between this look-up and the request is not caught by this; the platform's own
  refusal to reach private networks is the first line, this is the second.
- Calls that do not come from the service's own page: a different `Origin`, no `X-Requested-With: caw-frontend-verify`,
  a body that is not JSON or is larger than 1 KB. No CORS header is ever sent.
- More than 10 checks a minute from one address, or 300 a minute in all.

Reading a site is bounded: no redirects, 2 MB for `index.html` and 8 MB per script, 10 seconds per request and 25
seconds in all, at most 8 preloaded files and only when an address is still missing, and a list of unexpected
addresses is cut at 100 (the total is given). If a site needs more than the limits, the answer is "unreadable", never
a match.

## Safety notes you should know

- The rate limit inside the service is per running copy and approximate. It is a second line behind the platform's
  own daily limit (Free plan: 100,000 requests a day, after which the service stops until the next day; nothing is billed).
- `wrangler.toml` has a rate-limit binding ready, commented out. It is shared by all copies in a location, so it is
  the better limit; whether the Free plan allows it was not confirmed.
- The service makes requests to sites that others name. It says who is asking (`caw-frontend-verify-hosted/0` and the
  address of this repository). A site operator who does not want to be checked can block that name.

## Tests

`npm test` (Node 22; no dependencies are needed to test): 33 tests on the check (the same situations as the Python
tool's tests, plus extra address only, preloads, limits), on the address rules (about 70 inputs), the IPv4 and IPv6
classification, the bounded reading (redirect, status, size, stalls, timeouts, no detail of the other side in any
message), the name look-up, and the entry point (every refusal happens before any outside request, limits, cache,
no leak of internals). On real sites the result is the same as the Python tool's
(`cawnest.com`: 15 of 15, a match; `caw-testnode.com`: 5 of 15, 10 missing, 7 not in the build).

`make_data.py` makes `src/data.json` (the published addresses and the names shown to a reader) from
`../references/`; `python3 make_data.py --check` says whether it is up to date, and a test recomputes it independently.

## Deploy (Cloudflare account needed)

```sh
cd hosted
npm install                 # wrangler
npx wrangler login
npx wrangler deploy         # prints the address, https://caw-frontend-verify.<your-subdomain>.workers.dev
```

Things to check on the first day, because they could not be checked before deploying:

1. The page opens and the box for the address appears (the Worker answers `/api/info`).
2. `cawnest.com` gives a match and `caw-testnode.com` a difference.
3. A name that points at a private address is refused (for example `127.0.0.1.nip.io`).
4. The second check of a site within five minutes shows `x-cache: hit` (whether the Cache API works on `workers.dev` was not confirmed;
   without it the memory of one running copy is used).
5. The CPU time per check in the Cloudflare dashboard. The Free plan allows 10 ms per request; extracting the addresses
   from a 1.8 MB script took about 1.5 ms in Node, which leaves room, but the real figure is the one in the dashboard.
   If it is too high, the Paid plan ($5 a month at the time of writing) raises the limit.

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.
