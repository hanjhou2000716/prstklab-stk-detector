# Creator / FinancialJuice / News integration checkpoint

Date: 2026-08-21 (Asia/Taipei)

This checkpoint is based on the post-merge `main` HEAD `38f787a86b82573498f85b9d7c5d44b60d8244a6` and the public refresh run `32423165426`. It is an evidence ledger, not a claim that every external connector is configured.

## Canonical data path

`ingress → provider parser → sanitized observation → domain evidence → dedup/consensus → release manifest/hash gate → Pages → Mini App/Telegram → delivery receipt`

The producer is the source of truth. Release-time normalization is migration-only and must remain empty for newly produced records.

## Integration matrix

| Module | Code | Tests | Pipeline | JSON | Mini App | Telegram | Status |
|---|---|---|---|---|---|---|---|
| Creator registry/adapters | yes | yes | yes | yes | yes | partial | production |
| Creator consensus | yes | yes | yes | yes | yes | partial | production |
| Creator morning batch | yes | yes | yes (morning slot) | yes | yes | partial | partially_integrated |
| FinancialJuice parser/priority | yes | yes | yes when sanitized bundle exists | yes | yes | yes | production |
| FinancialJuice Gmail ingress | yes | yes | Railway only | sanitized only | source health | no direct send | partially_integrated |
| News source registry/ranking | yes | yes | GitHub Actions | yes | yes | yes | partially_integrated |
| Event cluster/consensus | yes | yes | yes | yes | yes | yes | production |
| Release manifest/hash gate | yes | yes | yes | yes | yes | gate | production |
| Railway source health | yes | yes | yes | health endpoint | health card | receipt | production |
| Telegram delivery receipt | yes | yes | yes | receipt | delivery status | yes | partially_integrated |

## Objective evidence

- Public manifest returned HTTP 200 with `status=ready`, release `release-b9feab1a16b46430`, market snapshot `d32d641f0c17474a`, research snapshot `research-8b8ec8f6e5ee51aa`, event snapshot `event-a889bf10a4141a3b`.
- All seven manifest-bound public artifacts returned HTTP 200 and matched their manifest SHA-256 hashes.
- Post-merge main regression: `1293 passed, 1 skipped`.
- `python -m src.runtime_audit` returned exit code 0. Its warnings remain explicit: local checked-in artifacts are not the public ready release, and local source gaps are not evidence of no risk.
- Railway `/health` returned HTTP 200 with privacy-safe `creator`, `financialjuice`, and `news` source-health sections.

## External gates still open

These are not silently promoted to `PASS`:

1. Railway Gmail OAuth/Pub/Sub is not configured (`configuration_missing`); no live Creator/FJ ingress evidence can be claimed.
2. `RAILWAY_STATUS_SHARED_SECRET` canonical migration still needs the operator to set the existing secret in Railway; values are never copied into source or logs.
3. GDELT currently reports a bounded source failure/429 state; stale fallback is not promoted to a live event.
4. A real single-recipient Telegram delivery receipt and Mini App WebView evidence must be captured after the operator enables the production-safe test path.

## Regression note

The Creator morning batch now rejects rows whose `published_at` or `received_at` is later than the release snapshot `as_of`. This prevents future rows from contaminating an earlier release and preserves point-in-time semantics.
