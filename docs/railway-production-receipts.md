# Railway production delivery receipts

GitHub Actions delivery receipts are signed with `RAILWAY_STATUS_SHARED_SECRET`
and include `release_id`, `snapshot_id`, `alert_id`, `delivery_mode`, and the
explicit `receipt_origin=github_actions` marker. Railway accepts a production
receipt that has this complete immutable tuple even when the monitor has not
created a matching outbox row first; the signed callback creates the row and
then stores the aggregate and per-recipient receipt.

Receipts without the origin marker, release metadata, or a supported delivery
mode remain rejected. This keeps unknown or misrouted callbacks fail-closed
while allowing scheduled and official monitor workflows to persist their
delivery result. The existing scoped `photo_smoke` contract remains unchanged.

## Verification

```text
python -m pytest -q tests/test_railway_monitor.py tests/test_photo_smoke_receipt.py tests/test_delivery_callback.py
python -m pytest -q
```

## Rollback

Revert this PR. Existing outbox rows and stored receipts remain readable; only
new production callbacks return to requiring a pre-created outbox row.
