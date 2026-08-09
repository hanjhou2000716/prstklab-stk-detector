# PRStK production baseline — 2026-08-09

This snapshot is the evidence baseline used by the TXT upgrade.  It records
what is actually deployed, rather than treating a file that exists in the
repository as production functionality.

## Immutable references

| Reference | Value |
|---|---|
| `MAIN_HEAD_SHA` | `47d2c608dfca78b3661c2ccb2e1476109f5a51d7` |
| `DATA_RELEASE_HEAD_SHA` | `fe608fb590e7909bc5bd2bffd906d7214893e882` |
| Public release | `release-d9ca5e04b57bf22b` (`ready`) |
| Market snapshot | `3a9a356d1a2a1688` |
| Research snapshot | `research-05c7ae8487b01350` |
| Event snapshot | `event-aef6826d45327217` |
| Policy | `2026.08` |

The public manifest artifact hashes are retained in `site/data/release-manifest.json`;
this document does not duplicate or override them.

## Current product state

| Area | Reality at baseline | State |
|---|---|---|
| Release gate | Local hashes and public manifest verification are enforced before delivery | production |
| Data release | Immutable `data-release` branch is the high-frequency data owner | production |
| Telegram | Production paths use one text message plus deep-link button; photo is scoped smoke only | production |
| Renderer | Explicit visual smoke/diagnostic path; not a production dependency | experimental |
| Source health | Legacy status fields exist; canonical taxonomy is introduced by the upgrade PRs | partially_integrated |
| Research | Full-universe scans publish explicit building/failed/no-candidate states | partially_integrated |
| Market freshness | Per-card freshness is available; hard alert gate is introduced by the upgrade PRs | partially_integrated |
| Mini App | Public release fallback and technical details are present; acceptance coverage is being extended | partially_integrated |

## Safety boundary

No PR in this upgrade authorizes automatic trading, private account access,
secret disclosure, stale high-risk alerts, candidate-threshold relaxation, or
automatic merge to `main`.  A partial scan is never represented as a complete
scan, and a missing optional API key is not represented as a core market fault.

## Rollback

Rollback is always an immutable release rollback: restore the last manifest
with `status=ready` and matching artifact hashes.  Do not copy individual JSON
files across releases and do not force-push `main` or `data-release`.
