# Zero-cost delivery receipt backend

Telegram delivery receipts now have a Cloudflare Worker/Supabase path that
does not depend on a running Railway service. GitHub Actions sends a signed,
privacy-safe aggregate receipt to `POST /api/delivery-receipt`; the Worker
verifies the HMAC and writes one idempotent row to
`delivery_receipt_events`. Only recipient hashes are stored—raw chat IDs and
bot tokens never leave the sender.

The same Worker is also the canonical Creator idempotency-history reader:
`POST /api/creator-delivery-history` accepts the same HMAC boundary and returns
only bounded, deduplicated `notification_keys` from Creator receipt rows. The
Creator dispatcher derives this route from `RECEIPT_CALLBACK_URL`, so it does
not require a live Railway service for duplicate protection. Railway remains
an explicit rollback reader when the Worker history endpoint is unavailable.

## One-time setup

1. Apply `supabase/migrations/202608280001_delivery_receipt_events.sql` to the
   Supabase project.
2. Deploy the Worker with the secret variable
   `DELIVERY_RECEIPT_SHARED_SECRET`.
3. Add the same value as a GitHub Actions secret with the name
   `DELIVERY_RECEIPT_SHARED_SECRET`. Do not put it in source control, logs, or
   this document.
4. Add the repository variable
   `RECEIPT_CALLBACK_URL`, for example:
   `https://<worker-host>/api/delivery-receipt`.

`RAILWAY_STATUS_URL` and its existing secret remain supported as an optional
rollback. When `RECEIPT_CALLBACK_URL` is present, it is preferred. If the
Worker returns an error or times out, Actions makes one bounded fallback
attempt to Railway using Railway's own secret; the two signatures are never
shared implicitly. If neither endpoint is configured, the callback is
explicitly skipped and the delivery step reports that no receipt backend is
available.

## Guarantees and failure handling

- HMAC is `sha256=<hex>` over the exact UTF-8 JSON body.
- The Worker rejects missing/invalid signatures, malformed JSON, oversized
  payloads, unknown status values, negative counts, and inconsistent counts.
- `trace_id` is unique, so retries are idempotent and cannot create duplicate
  aggregate receipts.
- A Supabase outage returns a generic `503` without exposing database details;
  Actions can retry or fall back to Railway. The Worker `/api/health` response
  exposes only `receipt.backend` and `receipt.configured`, never the secret.
- The existing per-recipient `delivery_receipts` table remains unchanged for
  Worker `/api/send` responses.
- Creator history queries are read-only, require `receipt_kind=creator`, and
  never return message text, media, raw chat IDs, or transport secrets.

## Verification

Use the local dry-run first:

```text
python -m src.delivery_smoke_test
```

For a controlled canary, set `RECEIPT_CALLBACK_URL`,
`DELIVERY_RECEIPT_SHARED_SECRET`, and the receipt fields in a workflow run.
Confirm the returned `trace_id` in Supabase, then repeat the same trace to
verify that the row is updated rather than duplicated. Do not broadcast a
test to production recipients.

For Creator idempotency, a signed request body such as
`{"receipt_kind":"creator","limit":200}` to
`/api/creator-delivery-history` should return only notification keys. A `503`
is treated as unavailable and causes a bounded Railway fallback; it is never
treated as evidence that no Creator episode was delivered.

## Rollback

Remove `RECEIPT_CALLBACK_URL` from repository variables to return to the
Railway callback, or temporarily disable the Worker secret. No public market
data or Telegram delivery release is modified by this receipt migration.
