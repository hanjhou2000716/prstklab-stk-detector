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

The 10:30 Asia/Taipei Creator batch is now backed by `src/schedule_contract.py`.
GitHub Actions uses a dedicated 02:30 UTC run, with 03:45 and 05:15 UTC
rechecks for bounded late arrivals. The ordinary 06:00 market briefing remains
separate; Creator delivery remains release-gated and opt-in.

### Railway health projection extraction (PR #675)

The public Railway health projection is now isolated in
`railway-monitor/source_health_projection.py`. The adapter uses an explicit
allow-list for Creator and FinancialJuice counters and timestamps; raw mail
bodies, Gmail message IDs, sender metadata and future private transport fields
cannot cross into `/health`. Missing or malformed diagnostics still fail soft
to an empty projection. Targeted Railway monitor, Gmail gateway and projection
tests passed (`109 passed`), and the standalone monitor compiled successfully.
This remains `partially_integrated` until the PR is merged and a post-merge
Railway health response is captured.

### Railway health-state boundary (PR #676)

The monitor's mutable health dictionary and lock now live in
`railway-monitor/health_state.py`; `app.py` retains a compatibility import and
the same endpoint contract. `snapshot_health()` returns a detached JSON-safe
copy, so concurrent probes cannot mutate runtime state and the long-running
server no longer owns the health-state implementation. The health-state
regression suite covers detached snapshots, default fail-soft status and
thread-safe updates (`111 passed` across the Railway targeted suite).

### Railway health contract projection (PR #677, latest local commit 798fb77)

The public Creator and FinancialJuice health sections now use a typed,
bounded allow-list. Counters accept only non-negative values, identifiers and
statuses are scalar strings with a fixed length limit, and nested values are
discarded. The projection also exposes safe lineage and delivery fields needed
to determine whether a morning batch and its Telegram receipt belong to the
same release/snapshot, without exposing Gmail IDs, raw mail, recipients or
tokens. This is additive; missing diagnostics remain fail-soft and do not
block the market release.

The same contract now includes Gmail ingress operational counters: watch
expiration, last ingress/sync timestamps, pending parser queue, dead-letter
count, and a boolean indicating whether a history cursor exists. These fields
are allow-listed and bounded; Gmail history/message IDs, OAuth values, sender
addresses and message bodies remain private. Targeted Railway/Gmail/health
verification is `117 passed`, plus standalone compilation and Mini App/source
health regression checks. Live Gmail OAuth/Pub/Sub configuration is still an
external acceptance gate and is not claimed by this PR.

## Post-merge evidence: Railway secret boundary and delivery acceptance

Validated against main HEAD `6cc0a99ed3b41e2f0d1fda344bfe06b9ced030fe` after
PR #689 (`fix: unify Railway delivery secret boundary`). The repository now
uses one redacted secret resolver across Railway observation export, Creator
delivery history, delivery callback, smoke validation and scheduled workflows.
`RAILWAY_STATUS_SHARED_SECRET` takes precedence; the historical
`DELIVERY_STATUS_SHARED_SECRET` remains a migration fallback until Railway
reports `canonical_name_present=true`.

Evidence captured on 2026-08-21 (Asia/Taipei):

- Main full regression: `1328 passed`.
- Renderer/Mini App/photo contract suite with local Chromium: `20 passed`;
  `uv run python -m src.system_dry_run` reported `renderer_available=true`,
  `card_dimensions=1080x1350`, and mocked delivery `delivered`.
- Public Pages release smoke: `ok=true`, release
  `release-faaa5b86acfc0db3`, market snapshot `d244146e6209880c`, all seven
  manifest-bound artifacts downloaded and hash-verified.
- Scoped Telegram photo workflow `32462571678` on main: `photo_card_dimensions=1080x1350`,
  `photo_delivery_delivered=1`, `photo_delivery_failed=0`; Railway callback
  returned `accepted` for the masked trace.
- Railway `/health` then reported `delivery_status=delivered`, delivered `1`,
  failed `0`, `receipt_matches=true`, and a recent receipt age. No recipient
  identifiers or secret values were stored in this document.

Remaining external gates are intentionally still visible: Railway Gmail
OAuth/Pub/Sub configuration is missing, GDELT is bounded at HTTP 429 with no
stale promotion, and Railway still reports the legacy secret name until the
operator completes the canonical variable migration.
