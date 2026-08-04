# P0-06: Safe data publishing

High-frequency market, event, health, and research refreshes must not commit generated files to `main`. The workflows now restore and publish public data through a dedicated `data-release` branch.

## Contract

- `main` contains code, schemas, and small fixtures only.
- `data-release` contains only selected `site/data/**` artifacts and explicitly selected historical caches.
- A workflow restores the latest data branch before refresh, so news/event ledgers and cached observations are not reset to the checkout's old copy.
- The Pages artifact is built from the refreshed workspace and is deployed only after the release gate (for notification workflows).
- The publisher creates a data-only commit with a temporary git index and pushes it to `data-release`; it never stages application code or secrets.
- If the branch is unavailable, restore is a no-op and the workflow can bootstrap a first release. An empty publish is rejected.

## Workflow usage

```bash
python -m src.data_release --restore --branch data-release --include site/data
python -m src.data_release --publish --branch data-release --include site/data
```

Research additionally includes `data/taiwan-mops-pristine-history.json` and `data/sec-companyfacts-cache.json`. The branch is retained for rollback and can be inspected by release commit hash.

## Rollback

Pages can be redeployed from a previous `data-release` commit. Do not merge generated data back into `main`; restore the desired data-release commit and rerun the relevant Pages workflow. A failed data-release push fails the job before any Telegram delivery step.

## Limitations and follow-up

The branch is a transition store, not a full object-storage history. P1-02 will add an immutable raw-observation store and retention policy; until then, keep the branch protected and retain at least 30 days of release commits.