# caw-frontend-verify

Checks which code a CAW website is based on, and which contracts it connects to.

[CAW Protocol](https://github.com/GilgameshCaw/Caw) is a decentralized social network. Anyone can run a node and a
website (the frontend) for it, so a website that looks like CAW may or may not be built from a published CAW release,
and may or may not point at the contracts of that release. The small, read-only tools here compare a site with a
published release (at present the `master` branch of GilgameshCaw/Caw) and state what was found: which contracts
the site points at, and whether they are the release's. Not affiliated with, or endorsed by, the CAW project. A
passing check means "consistent with the reference", not "safe".

Status: prototypes. Two things can be checked: the contracts a site points at (**available**), and the files a site
serves (**planned**: it needs fingerprints of the files built from published code, which do not exist yet).
Three tools exist (`contract-check`, `bridge`, `frontend-check`), `verify` runs them together from a command line,
and a static page (`web/`) shows the results. A public trial instance of the contract check is described below. A
scheduled monitor is not part of this repository.

## Try it

An example instance of the contract check runs at **https://caw-frontend-verify.zinsanjp.workers.dev**. It is run by
one person, [zinsanjp](https://github.com/zinsanjp), as a trial. It is not run by the CAW project or by the Caw-Lab
organization that hosts this code, and it may change or stop.
Type the address of a CAW website: the service reads the site's main script and compares the contract addresses in it
with those of Gilgamesh's master branch (V2). It does not check the files yet, and one address may ask only a few
times a minute. A result states what was found; it is not a guarantee of safety.

**Contact.** To ask that a site is not checked, to report a problem, or for anything else about the instance, open an
[issue](https://github.com/Caw-Lab/caw-frontend-verify/issues) in this repository, or reach zinsanjp through the
[GitHub profile](https://github.com/zinsanjp).

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
| [`hosted/`](hosted/) | a public service (Cloudflare Worker): the contract check for any site, behind the page of `web/` | tested; one trial instance runs (see Try it) |
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
