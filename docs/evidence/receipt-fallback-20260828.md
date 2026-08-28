# Receipt backend failover evidence — 2026-08-28

## Scope

This checkpoint records the canonical receipt path after the Cloudflare /
Supabase migration. The preferred target is the Cloudflare Worker endpoint;
Railway remains an optional rollback target.

## Local evidence

| Check | Result |
| --- | --- |
| Targeted callback and migration tests | 13 passed |
| Full isolated repository regression | 1502 passed |
| Ruff (callback and contract tests) | pass |
| Worker TypeScript typecheck | pass |
| PR #805 quality and delivery dry-run | pass |

The callback signs the Worker and Railway attempts independently. A Worker
HTTP error or timeout causes one bounded Railway attempt when the Railway URL
is configured; if both fail, the delivery step fails explicitly and preserves
the original delivery result for retry. No raw recipient IDs, tokens, or
secrets are written to the receipt payload or logs.

## Live evidence and remaining gate

The public Worker health endpoint was reachable with HTTP 200 and reported
Supabase, report dispatch, and Telegram configuration healthy. A newly generated
random value was stored in both the Cloudflare Worker secret
`DELIVERY_RECEIPT_SHARED_SECRET` and the GitHub Actions secret with the same
name on 2026-08-28. The GitHub secret listing confirms the secret name and
timestamp without exposing its value; the Cloudflare settings page confirms the
Worker secret entry without exposing its value.

The secret synchronisation is **PASS**. The live `/api/delivery-receipt` route
still requires a controlled canary with a valid HMAC and a real receipt payload
before it can be marked fully verified. No valid receipt was submitted during
this configuration step, so no production receipt row or Telegram message was
created. The secret value must never be committed, logged, or included in this
document.

## Rollback

If the Worker is unavailable, leave `RAILWAY_STATUS_URL` and its existing
secret configured; Actions will use Railway for the receipt attempt. To
disable the zero-cost preference, remove the repository variable
`RECEIPT_CALLBACK_URL`. No market release or Telegram recipient list is
changed by this rollback.
