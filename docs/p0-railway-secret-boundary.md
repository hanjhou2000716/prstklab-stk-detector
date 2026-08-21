# Railway delivery secret boundary

All Railway observation and delivery-receipt callers use
`src.railway_secret.delivery_shared_secret()` instead of reading an environment
variable directly. The canonical name is `RAILWAY_STATUS_SHARED_SECRET`; the
historical `DELIVERY_STATUS_SHARED_SECRET` remains a temporary read-only
fallback so an existing Railway deployment does not silently lose receipts.

Canonical values take precedence when both names are present. Health output
contains only redacted presence and active-name metadata, never the secret.

## Migration

1. Create `RAILWAY_STATUS_SHARED_SECRET` in Railway with the same value as the
   current active secret.
2. Add the same value to the GitHub Actions secret with that canonical name.
3. Run the health and delivery smoke checks.
4. Remove the legacy Railway variable only after the receipt check is healthy.

If the canonical variable is absent, the fallback is intentionally retained;
it can be removed in a later breaking migration after all deployments report
`canonical_name_present=true`.

## Rollback

Restore the previous variable name/value and revert the boundary commit. No
public release artifacts or Telegram payloads contain the secret.
