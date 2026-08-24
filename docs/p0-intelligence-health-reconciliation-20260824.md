# P0 intelligence health reconciliation

## Scope

This change closes the observability gap between the private Gmail ingress
store and the public Railway health projection. It does not promote Creator
or FinancialJuice content to official market evidence, and it does not change
the release or alert gates.

## What is now observable

For FinancialJuice, `/health` can now distinguish:

- received and parsed counts;
- public observations and vendor-importance `>=8` observations;
- items eligible for the separate vendor-priority review lane;
- items still waiting for official or market confirmation;
- the last public `release_id`, `snapshot_id`, and `observation_id`;
- the timestamp of the latest high-importance item; and
- the last Telegram delivery status when a receipt has been attached.

These values are bounded counters, timestamps, release lineage identifiers,
and short statuses only. Gmail message IDs, message bodies, sender addresses,
attachments, and recipient IDs remain private and are never projected.

## Decision semantics

`decision` is deliberately not a risk decision:

- `no_new_content`: no public observation has arrived;
- `parsed_below_priority_threshold`: observations exist, but none have vendor
  priority metadata;
- `awaiting_confirmation`: a clustered item still lacks official confirmation;
- `priority_items_ready_for_release_review`: a vendor-priority item exists and
  must still pass the normal release, source, and notification gates.

The final state remains fail-closed. A vendor score cannot create an official
event, a market-sync proof, or a high-risk alert by itself.

## Evidence and regression

The targeted store/projection and FinancialJuice regression suite covers the
lineage fields, priority counters, pending confirmation state, and privacy
boundary. The public state is meaningful only after the Railway worker has
received a real Gmail event; `no_new_content` is an honest idle state, not a
claim that the source failed.

Rollback: revert this atomic change. Existing store rows remain compatible;
new fields default to zero/null/not-checked on older volumes.
