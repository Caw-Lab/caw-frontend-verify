# caw-frontend-verify

Experiment: does the CAW frontend build reproducibly on GitHub Actions? Stage 1 of a possible "reference hash from CI" setup. Nothing here is published or deployed.

## What the workflow does

`repro.yml` (manual run, input: a full upstream commit SHA, default `97cd13f3…`):

1. Three jobs fetch that commit from `GilgameshCaw/Caw` into separate directories on separate runners.
2. Each installs dependencies the way the installer does (`cli/src/steps/install.js`): `npm install --legacy-peer-deps` in `client/`, then `yarn install --ignore-platform` in the frontend directory.
3. Each runs `yarn build` with the same fixed inputs (`CAW_CLIENT_VERSION=repro`, `VITE_NETWORK_ID=1`, `VITE_PROJECT_ID=dummy-project-id`).
4. `a1` and `a2` use Node `22.23.4` (the version on the reference server); `b1` uses `22.12.0`, the lowest 22.x the dependencies allow. Upstream `.nvmrc` says `22.0.0` at `97cd13f3`, but `yarn install` fails on it (`yargs@18.1.0` needs `^22.12.0`), found in the first run.
5. A compare job reads the three `build-manifest.json` files and writes a table to the run summary.

## How to read the result

| Result | Meaning |
|---|---|
| a1 = a2 | same input gives the same output on two machines |
| a1 = a2 = b1 | the Node version (22.12.0 vs 22.23.4) does not matter here |
| a1 ≠ a2 | the build is not stable on CI; the summary lists the files and which packages differ between the installs |

The VPS comparison is a separate step (needs permission to create a throwaway worktree there).

## Known limits (not verified)

- The workflow has not been run. The install commands are copied from the installer, but a failure in `npm install` (for example a postinstall step) or in `tsc -b` is possible; the first run may need fixes.
- `npm install` may resolve differently on different days if the lockfile does not pin everything; the per-job package lists (`deps-*.txt`) are there to show that.
- Earlier local builds used `npx vite build` (without `tsc -b`) and a shared `node_modules`; this workflow uses `yarn build` and fresh installs, so a match here is a new result, not a repeat.

## Safety

No secrets are used and none should be added. The token is read-only. Values in the workflow are dummies.
