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

## Notification fan-out

`src/creator_dispatch.py` consumes the same `morning_batch` object; it does
not re-scan or re-classify Creator records. For a current-day batch it:

- sends one episode notification per selected Creator (photo when the
  validated private attachment is available, otherwise the existing explicit
  text-only degradation);
- sends one bounded digest with a release-bound Mini App deep link for a
  complete or partial batch;
- sends only the late Creator episode plus a `late_delta` digest when a second
  source arrives after the cutoff;
- sends nothing for `no_new_content`;
- records distinct episode, digest, and late-delta notification keys so a
  retry/restart cannot resend an already delivered item.

The digest contains batch metadata only (`received/expected` and state); full
Creator content remains in the public-safe release artifact and Mini App.

## Verification

`tests/test_creator_morning_batch.py` covers complete 2/2, partial 1/2,
late-arrival retention, previous-day exclusion, parser-failure separation,
order-independent idempotency, and release-hash binding. Dispatch tests also
cover the 2/2 episode-plus-digest fan-out and restart idempotency.

Rollback is an atomic revert of the batch contract and its briefing wiring;
the existing sanitized Creator release remains readable because the new field
is additive.
