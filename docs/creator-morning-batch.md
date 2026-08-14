# Creator 10:30 morning batch contract

The Creator lane now has a deterministic batch boundary in
`src/creator_morning_batch.py`. It consumes only sanitized, successfully
parsed records and never infers facts or market direction.

## Rules

- The batch date is evaluated in `Asia/Taipei`; the scheduled cutoff is
  10:30 local time.
- `published_at` determines the episode date. Previous-day and future-day
  records are rejected rather than silently carried into the next batch.
- One latest episode is retained per enabled, consensus-eligible creator.
- A record received after 10:30 is retained as `batch_late_arrival` within a
  bounded three-hour grace window.
- The result distinguishes `complete`, `partial`, and `no_new_content` and
  exposes missing creators, rejected records, and late arrivals.
- `batch_key` and `idempotency_key` are deterministic for the date and selected
  episode keys, so reruns with the same input cannot create a new batch.

The morning batch is attached to the lineage-bound Creator release only when
the briefing slot is `morning`. It does not alter the release gate, consensus
policy, or Telegram alert eligibility.

## Verification

`tests/test_creator_morning_batch.py` covers complete 2/2, partial 1/2,
late-arrival retention, previous-day exclusion, parser-failure separation,
order-independent idempotency, and release-hash binding.

Rollback is an atomic revert of the batch contract and its briefing wiring;
the existing sanitized Creator release remains readable because the new field
is additive.
