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

`npm test` (Node 22; no dependencies are needed to test): 34 tests on the check (the same situations as the Python
tool's tests, plus extra address only, preloads, limits), on the address rules (about 70 inputs), the IPv4 and IPv6
classification, the bounded reading (redirect, status, size, stalls, timeouts, no detail of the other side in any
message), the name look-up, and the entry point (every refusal happens before any outside request, limits, cache,
no leak of internals). On real sites the result is the same as the Python tool's
(`cawnest.com`: 15 of 15, a match; `caw-testnode.com`: 5 of 15, 10 missing, 7 not in the build).

### What running it in the Workers runtime showed

The tests run in Node, and Node is more permissive than the platform. Running the service in the local Workers
runtime (`wrangler dev --local`) found two things that no Node test could, both now fixed and covered by tests whose
fake `fetch` refuses what the platform refuses:

- the platform has no `redirect: 'error'` mode (only `follow` and `manual`); the name look-up used it and failed for every site;
- `fetch` called as a method of another object (`this.fetchImpl(...)`) throws "Illegal invocation".

In that runtime, on real sites, the answers equal the Python tool's (`cawnest.com` a match, 15 of 15; `caw-testnode.com`
5 of 15, 10 missing, 7 not in the build; `example.org` unreadable, HTTP 404), the second check is answered from the cache,
names that point at private addresses (`127.0.0.1.nip.io`, `169.254.169.254.nip.io`, `10.0.0.1.nip.io`, `192-168-0-1.sslip.io`)
are refused, static files are served with the security headers, and the files listed in `web/.assetsignore` are not served.
Not covered by that run: the box for the address in a browser over https (the page shows it only over https for this
service), the platform's own limits, and everything that depends on the real network of Cloudflare.

`make_data.py` makes `src/data.json` (the published addresses and the names shown to a reader) from
`../references/`; `python3 make_data.py --check` says whether it is up to date, and a test recomputes it independently.

## Deploy (Cloudflare account needed)

```sh
cd hosted
npm install                 # wrangler
npx wrangler login
npx wrangler deploy         # prints the address, https://caw-frontend-verify.<your-subdomain>.workers.dev
```

### First deploy (2026-11-13, Free plan, `workers.dev`)

Checked from outside on the deployed service:

1. The page opens over https and the box for the address appears; the result loader and the command example are hidden (checked with a browser).
2. `cawnest.com`: a match, 15 of 15. `caw-testnode.com`: 5 of 15, 10 missing, 7 not in the build. `example.org`: unreadable (HTTP 404). The
   same as the Python tool. A check took about 3 to 5 seconds when the site was not in the cache, 0.2 seconds when it was.
3. Names that point at private addresses (`127.0.0.1.nip.io`, `169.254.169.254.nip.io`, `10.0.0.1.nip.io`) are refused.
4. The second check of a site is answered with `x-cache: hit`. Whether this comes from the platform's cache or from the memory of one running copy is not known.
5. The static files are served with the security headers; `README.md`, `sample-status.json`, `test/` and the other ignored files are not served.
6. A call without the `X-Requested-With` header, with a foreign `Origin`, with another method, an `http://` address and an IP address are all refused.

Not confirmed: the CPU time per check (the dashboard shows it; the Free plan allows 10 ms and none of the checks above was
stopped for exceeding it, which is evidence, not proof), the rate-limit binding on the Free plan (not enabled; the limit
inside the running copies is what works now), and the platform's own refusal to reach private networks (the name look-up
refuses them first, so it was not exercised).

License: MIT, see [`../LICENSE`](../LICENSE). Copyright (c) 2026 zinsanjp and contributors.
