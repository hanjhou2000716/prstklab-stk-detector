# Production acceptance evidence — 2026-08-15

This record is deliberately limited to observed evidence.  A successful
workflow run does not imply that every optional provider or long-running
Railway boundary is healthy.

## Controlled Telegram photo smoke

- Workflow: [31888691399](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31888691399)
- Job: `send-test-message` (`95021607003`)
- Scope: one explicitly supplied test recipient; no broadcast fan-out
- Renderer: Chromium installed by the workflow
- Card dimensions: `1080x1350`
- Delivery result: `delivered=1`, `failed=0`
- Railway callback: accepted
- Trace: `photo-smoke-7fe532a75d8a441f`
- Receipt status: `delivered`
- Receipt counts: `delivered=1`, `failed=0`, `recipient_count=1`
- Receipt correlation: `receipt_matches_last_outbox=true`

The workflow log is the source of truth for the card dimensions and delivery
counts.  Railway `/health` subsequently reported the same trace, a delivered
outbox, zero retryable deliveries and zero failed-recipient hashes.  No token,
chat ID, or private Telegram response is recorded here.

## Pages release evidence

The user-approved refresh-dashboard workflow
[31889221737](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31889221737)
completed successfully in 1m19s.  It refreshed market data, rebuilt the
immutable release, validated cache-busted assets, and deployed Pages.  The
public manifest was then fetched with a cache-busting query.

The public manifest was fetched after the smoke run and returned HTTP 200 with
`status=ready`:

| Field | Observed value |
|---|---|
| `release_id` | `release-6a168d17f803d4aa` |
| market snapshot | `ddc440bf9ccee7b5` |
| research snapshot | `research-8b8ec8f6e5ee51aa` |
| event snapshot | `event-f67c25c9f5e6f24d` |
| created at | `2026-08-15T22:12:24+08:00` |

This confirms manifest availability and lineage only; it does not claim that
all market observations are live or that formal backtest data is available.

## Railway health observed after callback

The health endpoint returned HTTP 200 and `status=ok`.  The delivery projection
showed:

- `last_receipt_status=delivered`
- `last_receipt_trace_id=photo-smoke-7fe532a75d8a441f`
- `receipt_matches_last_outbox=true`
- `retryable_count=0`
- `due_retry_count=0`
- `last_failed_count=0`

The same response still reported independent external conditions: GDELT
`invalid_json`/HTTP 403 health dispatch, Gmail `configuration_missing`, and
the canonical Railway delivery-secret migration flag.  Those are not hidden
by this successful Telegram test and remain open production follow-ups.

## Gate interpretation

This closes the controlled single-recipient photo delivery evidence for the
current main release.  It does **not** close:

1. Railway restart/volume continuity after a process restart;
2. Gmail OAuth/PubSub configuration and live Creator/FinancialJuice ingress;
3. a human visual confirmation inside Telegram or the Mini App WebView;
4. formal point-in-time backtest availability.

The release gate remains fail-closed for stale, unverified, or renderer-failed
data.  A renderer failure must record an error receipt and send no black card.
