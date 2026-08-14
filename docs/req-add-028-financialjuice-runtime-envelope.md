# REQ-ADD-028 — FinancialJuice sanitized runtime envelope

## Scope

The scheduled external-observation boundary now accepts the already reviewed
FinancialJuice compound envelope emitted by the existing parser. It fans out
each public-safe item into the shared event pipeline without introducing a
second classifier or delivery path.

## Safety contract

- `parse_status` must be `parsed`, `content_origin` must be `financialjuice`,
  and the envelope must be marked `public_safe`.
- `item_count` must equal the number of items.
- Every item must contain a unique `item_id`, a 64-character lowercase
  `content_hash`, an `event_cluster_key`, a candidate event type, and a
  headline.
- Raw/private fields and unresolved compound envelopes fail closed.
- The envelope `message_id` is transport metadata and is never copied into a
  published observation. `item_id` is the downstream observation identity.

## Verification

The loader tests cover accepted compound items, count mismatch, unresolved
parsing, duplicate/invalid item identity, private-field rejection, and
backward-compatible flat observation input. Full repository regression remains
the merge gate; Railway/Pages/Telegram acceptance remains an external gate.

## Rollback

Revert the atomic commit for this requirement. Existing flat observation input
and the shared event pipeline remain available; no release or notification
data is deleted by the rollback.
