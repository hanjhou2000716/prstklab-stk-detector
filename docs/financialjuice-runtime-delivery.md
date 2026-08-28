# FinancialJuice scheduled delivery boundary

FinancialJuice observations now use the same release-gated `sendPhoto` path as
other scheduled events. `src/scheduled_delivery.py` projects the reviewed
observation into the release event lane, then delegates qualifying items to
`deliver_financialjuice_event`.

The boundary is intentionally conservative:

- vendor importance `>= 8` enables vendor-priority notification only; it never
  changes the PRStK risk level;
- the release gate must be ready before rendering or sending;
- the event ledger stores the notification key and redacted per-recipient
  receipts, allowing a retry to target only recipients that did not succeed;
- renderer or Telegram failures remain visible as blocked/failed delivery
  evidence and never become a successful release;
- sanitized Railway/Gmail observations remain opt-in and raw mail is never
  persisted in the public release.

## Verification

The scheduled delivery integration is covered by the focused offline suite:

```text
python -m pytest -q tests/test_scheduled_delivery.py \
  tests/test_event_ledger.py tests/test_financialjuice_notification_e2e.py \
  tests/test_financialjuice_priority.py tests/test_financialjuice_release_contract.py
36 passed
```

This is local/mock evidence only. A live Railway observation and a production
Telegram receipt still require the corresponding external configuration and a
controlled single-recipient acceptance run.

## Rollback

Reverting the commit that binds `deliver_financialjuice_event` restores the
previous generic scheduled sender. Existing release and risk gates remain
unchanged; no secret or raw message content is part of this change.
