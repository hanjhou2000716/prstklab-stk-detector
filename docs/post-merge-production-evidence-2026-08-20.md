# Post-merge production evidence — 2026-08-20

This checkpoint records the evidence collected after the Railway canonical
parser bundle was merged. It does not convert unavailable external services
into a successful acceptance result.

## Main and Actions

| Item | Evidence | Result |
|---|---|---|
| Main commit | `f73500789aae10c4543acce80a00ece0ad6ab201` | merged |
| Canonical parser PR | PR #641 | merged |
| Quality and delivery dry-run | run `32361739398` | success |
| Security and supply-chain checks | run `32361739386` | success |
| Refresh market dashboard | run `32362265475` | success |

The refresh run completed market refresh, immutable data-release publication,
static asset validation, Pages upload, and Pages deployment.

## Public Pages release

The cache-busted public manifest returned HTTP 200 after the refresh:

- `release_id`: `release-1c15de259d0044d6`
- `status`: `ready`
- `market_snapshot_id`: `5eb1dd579349fc73`
- `research_snapshot_id`: `research-8b8ec8f6e5ee51aa`
- `event_snapshot_id`: `event-ed531dee05c7de49`
- `creator_status`: `ready`
- `news_status`: `ready`
- `validation_errors`: none

The release is internally consistent at the manifest level. This is evidence
of the published artifact and lineage, not evidence that every upstream
provider is healthy.

## Railway health

Read-only request to the configured Railway `/health` endpoint returned HTTP
200 with `status=ok`:

- runtime: `healthy`
- classifier mode: `repository-shared`
- Jin10: `healthy`, heartbeat healthy
- GDELT: `failed`, `HTTP_429`; bounded retry metadata present
- health callback: `HTTP_403` permission denied
- Gmail/Creator ingress: `configuration_missing`
- delivery: `not_checked`

The GDELT and callback failures remain visible and fail closed. They must not
be reclassified as `no_event`, and they cannot authorize a high-risk alert.
Gmail/PubSub configuration and a controlled delivery receipt are still
external acceptance prerequisites.

## Verification

- Railway/parser/FinancialJuice focused regression: **120 passed**.
- `sync_railway_canonical_parser.py --check`: passed.
- Main-branch post-merge runtime audit: `ok=true` (warnings remain for the
  unavailable production event/research artifacts in the local checkout).
- Telegram delivery dry-run with a non-production placeholder recipient:
  passed; no real recipient was contacted.
- The merged CI workflow also completed the repository unit test, coverage,
  Ruff, Mypy, compile, release-to-delivery dry-run, and offline acceptance
  steps successfully.

## Acceptance state

Overall production acceptance remains **INCOMPLETE / NEEDS_REVERIFY** until all
of the following have objective evidence:

1. Gmail OAuth/PubSub ingress receives and parses a sanitized Creator or
   FinancialJuice observation in Railway.
2. GDELT provider and GitHub health callback credentials are corrected, or a
   documented external outage is resolved.
3. One explicitly controlled Telegram recipient receives a release-gated
   message and its Railway delivery receipt matches the same release,
   snapshot, and observation IDs.

No code path was loosened to hide these gaps, and no production broadcast was
sent during this checkpoint.

