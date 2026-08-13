# P0 Alert Notification Identity

Budget decisions, event-ledger delivery rows and external compound results
now expose the same `notification_id`. Explicit alert IDs take precedence;
FinancialJuice compound items use their stable item ID; other events use the
canonical event cluster. This prevents a transport message or source URL from
silently changing cooldown/budget identity.

The existing fail-closed quality, release and cross-check gates are unchanged.
