# Production merge and verification runbook — 2026-08-13

This runbook records the current stacked reliability work after PR #478 was
merged. The stack remains unmerged until the repository owner reviews each PR.
Use **Create a merge commit** and keep dependent branches until their parent
has passed its post-merge checks.

## Current creator-data stack

The creator enrichment path is intentionally optional and public-safe. It does
not ingest private media, raw email, or credentials. Merge in this order:

| Order | PR | Depends on | Scope |
|---:|---:|---:|---|
| 1 | #523 | #522 | Creator source-health states and delivery E2E boundary |
| 2 | #524 | #523 | Creator intelligence release producer |
| 3 | #525 | #524 | Briefing binding for sanitized creator insights |
| 4 | #526 | #525 | Creator artifact publication path |
| 5 | #527 | #526 | Public loader and creator artifact hash gate |
| 6 | #528 | #527 | Sanitized creator records in manifest build |
| 7 | #529 | #528 | Optional scheduled creator input |
| 8 | #530 | #529 | Scheduled briefing binding |
| 9 | #531 | #530 | Creator input in release identity |
| 10 | #532 | #531 | Production integration matrix |
| 11 | #533 | #532 | Normalized creator release identity |
| 12 | #534 | #533 | Offline production E2E creator release contract |

PRs #500–#522 are the preceding source, release, event, and research stack;
they must be merged before #523. PR #478 is already merged and is the strategy
matrix baseline for this sequence.

## Verification gate

After all dependent PRs are merged, run the following in order:

1. Refresh market and research snapshots.
2. Build and validate a `status=ready` release manifest.
3. Deploy Pages and verify the public manifest, snapshot IDs, and artifact
   hashes match.
4. Run `python -m src.production_e2e` in the CI renderer environment.
5. Run the scoped photo smoke test with one explicitly approved test chat ID.
6. Inspect the Railway delivery receipt for the same `release_id`,
   `snapshot_id`, `observation_id`, and trace ID.

The production E2E is offline by design. It proves release lineage and the
creator delivery contract without contacting Telegram, Railway, Gmail, or an
external creator provider. A real Telegram test is a separate, explicit,
single-recipient action.

## Failure and rollback

- A missing or invalid creator artifact must not invalidate the parent market
  release; the Mini App shows the creator section as unavailable.
- A creator artifact with a mismatched parent release is rejected by the release
  gate and must never be sent.
- If Pages verification fails, keep the previous successful release active and
  do not notify recipients.
- If the renderer fails, do not send a black or fallback photo; inspect the
  receipt and retry only after the renderer check passes.
- Roll back by restoring the previous `status=ready` manifest and reverting the
  stack in reverse order. Never mix artifacts from different releases.

## Local quality evidence

On the latest creator E2E branch, the full suite passes with 936 tests and
81.90% coverage; Ruff, mypy, bytecode compilation, JavaScript syntax, and the
runtime audit pass. Runtime-audit warnings about missing live snapshots are
expected for a local fixture and are not evidence of a production release.
