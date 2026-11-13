# caw-frontend-verify

Small, read-only tools to check that what a CAW node serves and points at is what a published
reference says it should be. Not affiliated with, or endorsed by, the CAW project. A passing check
means "consistent with the reference", not "safe".

Status: prototypes. The three checks exist (`contract-check`, `bridge`, `frontend-check`) and `verify` runs them together from a command line; a static page (`web/`) shows their results; a scheduled monitor does not exist yet.

## Try it

An example instance of the contract check runs at **https://caw-frontend-verify.zinsanjp.workers.dev**. It is run by
one person, the author of this repository, as a trial. It is not run by the CAW project, and it may change or stop.
Type the address of a CAW node: the service reads the site's main script and compares the contract addresses in it
with those of Gilgamesh's master branch (V2). It does not check the files yet, and one address may ask only a few
times a minute. A result states what was found; it is not a guarantee of safety.

The service is a Cloudflare Worker: anyone with a Cloudflare account can run the same one (see [`hosted/`](hosted/README.md)).
A version for an ordinary server is not provided yet. It would need more protection against requests to internal
addresses than the platform gives (see `hosted/README.md`). The checks themselves run anywhere with Python 3; to run
them on your own computer or server:

```sh
git clone https://github.com/Caw-Lab/caw-frontend-verify.git
cd caw-frontend-verify/verify
python3 verify_site.py cawnest.com     # from the command line
python3 serve_local.py                 # or a local page with a box for the address
```

## Layout

| folder | what | status |
|---|---|---|
| [`contract-check/`](contract-check/) | compares the contracts a deployment points at (code, links, owners, libraries) with a contract reference, through public JSON-RPC | prototype (Python, standard library only) |
| [`frontend-check/`](frontend-check/) | compares the files a node serves with a frontend manifest (SHA-256 per file) | prototype (Python, standard library only) |
| [`bridge/`](bridge/) | joins the two: the contract addresses compiled into a frontend's entry script are compared with an address fingerprint of a reference build (which contracts does this frontend point at?) | prototype (Python, standard library only) |
| [`verify/`](verify/) | runs the three checks for a site against a release registry and states the facts side by side (no ranking) | prototype (Python, standard library only) |
| [`hosted/`](hosted/) | a public service (Cloudflare Worker): the contract check for any site, behind the page of `web/` | written and tested; not deployed yet |
| [`web/`](web/) | a static page that shows results in English and Japanese; with `verify/serve_local.py` it has a box where a site address is typed | first version (HTML and JavaScript, no dependencies) |
| [`.github/workflows/repro.yml`](.github/workflows/repro.yml), [`scripts/`](scripts/) | builds one published commit of the upstream frontend on several GitHub Actions runners and compares the build manifests; the way to get file fingerprints that the frontend file check will need | experiment (stage 1), see [`docs/reproducibility.md`](docs/reproducibility.md) |
| [`formats/`](formats/) | specifications of the reference files, the release registry and the status file | contract reference, release registry and status file: v1; others: drafts |
| [`references/`](references/) | reference data (addresses and hashes: facts about public chains) | testnet set for upstream commit `97cd13f3` |

Each tool folder stands on its own: it has its own README and tests, and does not import from the
others. Only `bridge/` connects them.

## Why two checks

A frontend manifest can say "this screen points at address set A". It cannot say that A is the
genuine deployment. The contract reference can say that A is consistent on the chains. Both together
support "the contracts this screen points at are the ones in the reference". Neither says anything
about a node's backend or its configuration.

## Provenance

Original code, written from scratch (see each tool's README for the inputs it uses). Nothing was
copied from the upstream Verifier, from other pull requests, or from other projects.

This repository contains no code of the CAW client. The workflow in `.github/workflows/repro.yml`
fetches a published upstream commit at run time and builds it in a temporary directory; what is kept
and published is only file names, hashes and package lists. Built files are not stored or published,
and no file of the upstream repository is copied into this one. Contract addresses and chain state
are public facts read at run time.

## License

MIT, see [`LICENSE`](LICENSE). Copyright (c) 2026 zinsanjp and contributors. Contributions are
accepted under the same license.
