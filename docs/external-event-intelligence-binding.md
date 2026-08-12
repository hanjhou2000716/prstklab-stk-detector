# Unified external event binding

`build_intelligence_context` now calls the same external event pipeline used by
live source handling. The scheduled briefing forwards all external story
fields, clusters source observations, and exposes each item’s lifecycle,
notification decision, and pending evidence reasons.

This is deliberately additive: the existing risk summary remains available,
while `external_event_risk.unified_events` is the auditable path for Mini App
and future alert cards. A FinancialJuice headline without official evidence or
market synchronisation stays pending and cannot become a high-risk Telegram
message.

Rollback: revert this binding commit; the existing conservative cluster score
continues to operate independently.
