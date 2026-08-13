# Creator runtime acceptance matrix

This is the acceptance record for the Creator notification lane.  It is
intentionally separate from market-event evidence: Creator content cannot
raise a market alert or bypass the market release gate.

| Check | Contract | Evidence |
|---|---|---|
| Source state | `configuration_missing`, `no_event`, `healthy`, `parse_failed`, `failed` | scheduled snapshot `source_health` rows |
| Release gate | parent manifest and Creator artifact must be `ready` with matching hashes | `src/creator_dispatch.py` |
| Delivery | photo when approved media exists; bounded text fallback otherwise | `src/creator_notification.py` |
| Idempotency | notification key checked against local and signed Railway history | `src/creator_delivery_store.py` |
| Receipt | release, snapshot, alert, mode, counts and notification keys | `src/delivery_callback.py`, Railway outbox |
| Privacy | no raw body, media path, token or Telegram ID in public artifacts | receipt/source-health tests |

Rollback is a branch revert followed by disabling
`CREATOR_NOTIFICATION_ENABLED`; the market-only release path remains
available.  Any production test must remain restricted to the approved test
recipient and use a release-gated artifact.
