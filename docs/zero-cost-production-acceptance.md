# Zero-cost production acceptance runbook

This runbook is the final gate for the Railway-to-Actions/Supabase/Cloudflare
path. It is intentionally separate from offline CI: a green unit-test job does
not prove that a provider-side deployment, public Pages release, or Telegram
delivery occurred.

The 2026-08-27 preflight found that the repository currently has Telegram
secrets but does not yet have the Supabase secrets, Worker URL, or Pages API
variable required for this canary. See the redacted
[preflight evidence](evidence/zero-cost-canary-preflight-2026-08-27.json).
Until those provider values are configured, the canary remains
`needs_provider_configuration` and Railway remains rollback-only.

## Required order

1. Apply `supabase/migrations/202608270001_report_jobs.sql` and
   `202608270002_delivery_receipts.sql` in the intended Supabase project.
2. Deploy `worker/` with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `GITHUB_DISPATCH_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TG_SUBSCRIBERS` and an
   explicit `ALLOWED_ORIGINS` value. Secrets are configured in the provider
   UI, never committed or printed.
3. Set `PUBLIC_API_BASE_URL` for the Pages deployment and publish a ready
   release. A failed manifest must leave the last known-good release intact.
4. Use a Telegram WebView session to create one report, then wait for the
   bounded job status to become `ready` or `failed`.
5. For the designated test chat only, send one release-bound `sendPhoto`
   request. Verify the response trace ID and query the delivery receipt by its
   trace ID; do not broadcast the test to the subscriber list.
6. Capture a redacted acceptance artifact containing the release, snapshot,
   alert, trace and receipt IDs, HTTP status, freshness, and the public URL.
7. Only after all checks pass may Railway polling be disabled. Preserve the
   previous Railway deployment and the previous Pages release until the first
   scheduled cycle completes successfully.

## Evidence checklist

The external acceptance report must record each item as `pass`,
`needs_reverify`, or `not_checked`:

- Supabase migrations applied and RLS enabled;
- Worker `/api/health` reachable over HTTPS;
- workflow dispatch accepted and job status observable;
- Pages manifest is `ready` and artifact hashes match;
- Mini App uses one release/snapshot lineage and resolves its deep link;
- renderer output is readable PNG `1080x1350`, not a single-color fallback;
- Telegram test recipient has one `sendPhoto` message;
- `delivery_receipts` contains the same trace/release/snapshot IDs;
- retry or failure paths are recorded without exposing secrets;
- Railway cutover decision and rollback target are recorded.

`not_checked` is not a pass. If any required item is `needs_reverify` or
`not_checked`, continue serving the last known-good release and keep Railway
enabled. This is fail-closed behavior, not an indication that no risk exists.

## Rollback

If the Worker, Supabase, Pages, renderer or Telegram canary fails, stop the
new dispatch path, restore the previous Pages release, and re-enable the
existing Railway schedule. Do not delete the old database rows or release
artifacts; they are needed to reconcile delivery receipts and investigate the
failure.

## Safety boundary

The acceptance run uses one explicitly designated test chat and a mocked or
dry-run transport for all other recipients. It never performs a trade, reads
private brokerage data, or stores Telegram tokens, chat IDs, raw email or raw
provider payloads in public artifacts.
