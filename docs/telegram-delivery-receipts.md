# Telegram delivery receipts

Cloudflare Worker `/api/send` now assigns a per-request `trace_id` and records
one privacy-safe receipt per configured recipient in Supabase. Only a short
SHA-256 recipient hash is stored; raw chat IDs, bot tokens and Telegram response
bodies never enter logs or the database.

Each receipt links the optional `alert_id`, `release_id` and `snapshot_id` to:

- `delivered`, `failed`, `retryable` or `blocked`
- Telegram `message_id` when available
- bounded `error_class`
- `sent_at`

HTTP 429 responses honour a bounded `retry_after` delay once. A recipient
failure is isolated from all other recipients. If Supabase receipt storage is
temporarily unavailable, the endpoint returns
`receipt_status=persistence_failed` so the caller does not mistake an
un-audited delivery for success.

## Rollback

Revert the Worker and migration commit. Existing Python Telegram delivery and
its release gate remain unchanged; the migration is additive and can be left
in place for audit history.
