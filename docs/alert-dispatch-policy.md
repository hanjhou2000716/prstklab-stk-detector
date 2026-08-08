# Alert dispatch policy

All formal Telegram paths use the same pre-send gate:

1. The incoming event is canonicalised and observed in the durable event
   ledger.
2. Existing successful reminders are projected into the shared alert-budget
   history.
3. The 30-minute cooldown, hourly cap, and per-event update cap are checked.
4. A risk upgrade or escalation may bypass cooldown, but never bypasses the
   release gate, source-quality checks, or the black-swan confirmation rules.
5. Only a successful delivery calls `record_dispatch`; failed sends therefore
   remain retryable without consuming the budget.

The policy is wired into the official-event monitor, scheduled brief, photo
brief, and manual emergency alert paths. A blocked event remains visible in
the Mini App/ledger with the exact reason (`cooldown`,
`hourly_budget_exhausted`, or `event_update_budget_exhausted`).

## Rollback

Revert the integration commit and keep the existing event ledger. The ledger
format is backward compatible: old records with only `last_reminded_at` are
read as one successful reminder and do not expose recipient identifiers.
