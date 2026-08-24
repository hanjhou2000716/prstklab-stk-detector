# Railway receipt and Gmail state persistence

The Railway monitor keeps delivery outbox/receipts, event ledger, seen IDs and
Gmail Watch cursors in SQLite. A writable path alone is not proof of durable
storage: a process restart can recreate `/data` inside a fresh container.

## Required production configuration

Attach a Railway Volume to the monitor service at `/data` and keep:

```text
MONITOR_STATE_PATH=/data/jin10-monitor.sqlite3
GMAIL_STATE_PATH=/data/gmail-ingress.sqlite3
```

The service health response now exposes a redacted `delivery.storage` record.
`status=ready` means the state directory is writable and is detected as a
mounted volume. `unknown` means the process can write a file but persistence has
not been proven; `unavailable` means it cannot write. External acceptance
remains fail-closed for both non-ready states, even if the latest receipt says
`delivered`.

## Verification after a restart

1. Record the current `/health` `delivery.last_trace_id` and
   `delivery.last_receipt_status`.
2. Restart or redeploy only the Railway monitor service.
3. Query `/health` again and confirm the same receipt trace is present,
   `receipt_matches_last_outbox=true`, and `delivery.storage.status=ready`.
4. Confirm the Gmail `watch_expiration` and history cursor remain present.
5. Run the read-only external acceptance collector. Do not send a production
   notification merely to test persistence.

If the trace disappears or storage is not `ready`, stop high-risk delivery,
attach/fix the Volume, and repeat the restart check. Do not promote the state
to `production` based on a single in-process receipt.

## Rollback

Revert the monitor release only after preserving the SQLite volume. Never delete
the volume during rollback; it is the audit source for delivery receipts,
deduplication and Gmail cursors.
