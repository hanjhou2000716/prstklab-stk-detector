# FinancialJuice production lane

FinancialJuice is a discovery/relay source.  The scheduled publisher now
projects every reviewed, public-safe item into the release-bound event lane:

```text
Railway/Gmail review
  -> sanitized observation
  -> FinancialJuice priority projection
  -> external event classifier / risk contract
  -> market snapshot + briefing + event artifact
  -> release manifest / Pages gate
  -> scheduled photo delivery
```

`vendor_importance >= 8` produces `vendor_priority_notification=eligible`.
This is a delivery-priority decision only; it never changes the PRStK risk
level.  The event remains `R2`/pending until the official-source and
market-synchronisation gates are independently satisfied.

Every item exposes an auditable decision in
`financialjuice_priority_decisions`, including `observation_id`, `item_id`,
`event_cluster_key`, vendor importance, PRStK risk, and the reason it was sent,
held, or deduplicated.  A matching cluster is marked
`already_cluster_notified` rather than sending a duplicate full alert.  Items
below 8 remain visible as `not_eligible`; they are not silently dropped.

Before `write_snapshot`, `src/financialjuice_release_contract.py` verifies
that every reviewed observation has one decision and that every eligible item
has a matching event with explicit vendor-risk separation.  A mismatch writes
only a blocked diagnostic and cannot reach Pages or Telegram.

The release gate and renderer still run before Telegram.  Missing or stale
market evidence therefore remains fail-closed, and the Mini App can explain
`等待官方核對` / `等待市場同步` without exposing private Gmail transport IDs.

Rollback: revert the projection commit.  Existing external observations remain
readable because the new fields are additive.
