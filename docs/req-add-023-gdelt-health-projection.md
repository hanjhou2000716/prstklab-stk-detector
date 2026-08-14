# REQ-ADD-023 GDELT source-health projection

## Scope

Project the existing GDELT fetch state into a stable Railway health envelope.
The adapter and alert gate are unchanged; this only makes the source outcome
explicit for operators and the Mini App health view.

## Semantics

- `healthy` + `event_scan=no_event`: the live/fresh scan completed with no
  qualifying article.
- `failed` + `event_scan=scan_failed`: the provider or parser failed; this is
  not evidence that no event exists.
- `fallback_active`: bounded stale cache is visible, but the monitor still
  suppresses new alerts from that cache.
- `not_checked`: no source result has been recorded yet.

The projection preserves article, alert and pending counts, bounded reasons,
market-sync status, stale-cache flag, and a type-only error label. It never
changes dispatch eligibility or creates a market direction.

## Verification and rollback

`tests/test_railway_gdelt_health.py` covers empty success, provider failure and
stale-cache paths. Reverting the atomic change restores the previous health
dictionary construction; the fetch and fail-closed alert behavior remain
unchanged.
