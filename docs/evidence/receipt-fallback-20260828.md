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
Supabase, report dispatch, and Telegram configuration healthy. At capture time,
the Worker settings did not contain `DELIVERY_RECEIPT_SHARED_SECRET`, so the
live `/api/delivery-receipt` route cannot yet be considered verified. This is
deliberately recorded as **NEEDS_REVERIFY**, not PASS.

To close the gate, create one new random shared secret and store it in both:

1. Cloudflare Worker secret `DELIVERY_RECEIPT_SHARED_SECRET`.
2. GitHub Actions secret `DELIVERY_RECEIPT_SHARED_SECRET`.

Then deploy the Worker and run the controlled single-receipt canary. The
secret value must never be committed, logged, or included in this document.

## Rollback

If the Worker is unavailable, leave `RAILWAY_STATUS_URL` and its existing
secret configured; Actions will use Railway for the receipt attempt. To
disable the zero-cost preference, remove the repository variable
`RECEIPT_CALLBACK_URL`. No market release or Telegram recipient list is
changed by this rollback.
