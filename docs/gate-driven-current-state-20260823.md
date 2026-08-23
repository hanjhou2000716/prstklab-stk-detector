# Gate-driven current state — 2026-08-23

This checkpoint is the evidence boundary for the Creator Intelligence V2,
FinancialJuice and news-integration work. It is evaluated from `main` at
`00ce6c79` (the merge commit for PR #711) and must not be confused with an
older historical audit note.

## Evidence captured from the repository

| Gate | Evidence | Result |
|---|---|---|
| Canonical provider/parser overlap | `python scripts/verify_canonical_overlap.py` and `python scripts/sync_railway_canonical_parser.py --check` | PASS — zero drift and all generated source hashes match |
| Python/JavaScript syntax | `python -m compileall -q src railway-monitor`; `node --check site/app.js` | PASS |
| Full local regression | `python -m pytest -q --basetemp=<isolated temp>` | PASS — 1330 passed, 1 skipped |
| Offline system dry-run | `python -m src.system_dry_run` | PASS — traceable release/snapshot/observation, 1080×1350 contract, deep link and fail-closed lifecycle |
| Latest immutable data release | `origin/data-release` at `8113589` | PASS — manifest `release-b97850898b5c2678`, status `ready`; production acceptance with the complete research matrix passed |
| Checked-in `main/site/data` | `python -m src.production_acceptance --manifest site/data/release-manifest.json --site-root site` | FAIL CLOSED — missing event/research snapshots and invalid status; it must not be used as a public release |

The immutable `data-release` result is the only local release candidate. The
checked-in `main/site/data` result is intentionally not promoted; the scheduled
workflow must restore the immutable branch before Pages publication.

## Canonical implementation status

The following are already implemented in the canonical pipeline and covered by
the repository test suite:

- Creator provider registry (`haojiao`, `jenny`, `gooaye`) with unknown-provider
  rejection and generated Railway bundle parity.
- Sanitized Creator/Jenny/FinancialJuice parsing, attachment provenance,
  privacy filtering, compound-item fan-out and vendor-priority separation.
- Creator morning batch metadata, consensus, correlation and release lineage.
- Shared event classification, evidence/lifecycle gating, deduplication and
  release-bound Mini App projections.
- Official-first news provider registry, market relevance ranking, URL safety
  and deduplication.
- Release manifest/hash gate, Pages-before-Telegram ordering, photo renderer
  contract, single-message deep links and delivery-receipt schemas.
- Gmail Watch creation/renewal code and privacy-safe health projection (PR #711).

No second Creator, FinancialJuice or event-classifier pipeline may be added.
Railway generated files must continue to be produced from the canonical `src/`
modules and `config/` JSON.

## External evidence still required

These are not local code failures and must remain `NEEDS_REVERIFY` until a
controlled, non-broadcast production check records objective evidence:

| Item | Required evidence | Safe state before evidence |
|---|---|---|
| Railway Gmail Watch | `/health` shows configured watch, renewal timestamp and a signed Pub/Sub cursor | `configuration_missing`/`stale`; never interpret as no email |
| FinancialJuice ingress | Sanitized Railway observation bundle reaches a release snapshot with parser and priority counters | source unavailable; no high-risk promotion |
| Official news refresh | TWSE/MOPS/SEC/Fed provider health and freshness in a ready public release | provider-specific failure; other providers continue |
| Pages/Mini App | Public manifest/hash/snapshot IDs match one ready release; no mixed artifacts | preserve previous successful release |
| Telegram | One explicitly scoped test recipient receives one release-gated photo and matching receipt | dry-run only; no broadcast |
| Railway restart/volume | Receipt, watch cursor and classification state survive a restart | retryable/unverified; do not claim continuity |

The absence of any of these observations must never be converted to `no_event`,
`healthy`, `confirmed` or `high-risk`.

## Rollback and continuation

1. Keep the previous successful `data-release` manifest available.
2. If a new manifest/hash audit fails, do not deploy Pages and do not notify.
3. If a renderer or Telegram delivery fails, retain the release and receipt
   error; retry only the failed recipient through the bounded outbox.
4. Configure the protected Railway/Gmail variables, run the controlled
   acceptance checks above, then update this checkpoint with URLs and receipt
   IDs (never tokens, message bodies or recipient lists).

This document is an evidence ledger, not a claim that external production
acceptance is complete.
