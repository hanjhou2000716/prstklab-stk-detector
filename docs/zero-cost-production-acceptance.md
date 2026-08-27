# Zero-cost production acceptance runbook

This runbook is the final gate for the Railway-to-Actions/Supabase/Cloudflare
path. It is intentionally separate from offline CI: a green unit-test job does
not prove that a provider-side deployment, public Pages release, or Telegram
delivery occurred.

The 2026-08-28 provisioning checkpoint created the canonical Worker at
`https://prstk-api.hanjhou2000716.workers.dev`. The deployed health endpoint
is reachable, but the canary remains
`needs_provider_secrets`: the Supabase service-role key, GitHub dispatch token,
and Telegram bot secret have not been entered into the Worker. See the redacted
[provisioning evidence](evidence/zero-cost-worker-provisioning-2026-08-28.json)
and the earlier [preflight evidence](evidence/zero-cost-canary-preflight-2026-08-27.json).
Until those provider values are configured, Railway remains rollback-only.

The canonical-overlap audit is independently recorded in
[canonical overlap evidence](evidence/canonical-overlap-audit-2026-08-28.json)
and currently reports zero drifted or duplicate canonical paths.
The subsequent full offline regression is recorded in
[Creator/FJ overlap regression evidence](evidence/creator-fj-overlap-regression-2026-08-28.json):
1493 tests passed, with only the expected non-ready sample-artifact warnings.

The pre-redeployment 2026-08-28 health recheck returned HTTP 200 with
`api: ok` and `database: unavailable`; it is retained as historical evidence in
[health recheck evidence](evidence/zero-cost-worker-health-recheck-2026-08-28.json).
The response was intentionally fail-closed and did not represent a successful
production canary or Telegram delivery.

The latest dashboard redeployment and public endpoint check are recorded in
[Worker deployment recheck evidence](evidence/zero-cost-worker-deploy-recheck-2026-08-28.json).
It confirms that `/api/health` is reachable and the current
`zero-cost-worker-1` health-classification source is deployed.  The response is
now explicitly `status=configuration_missing`; this proves source reachability
but is not a successful canary until the provider secrets are configured.
The earlier [public health evidence](evidence/zero-cost-worker-public-health-2026-08-28.json)
remains the pre-redeployment observation.

The latest read-only Pages/Worker comparison is recorded in
[public canary recheck evidence](evidence/zero-cost-public-canary-recheck-2026-08-28.json).
Pages currently exposes a `ready` manifest (`release-495be75d829e5b1b`), while
the Worker correctly remains `configuration_missing`.  These are deliberately
reported as separate states; a ready Pages manifest alone does not authorize a
Telegram canary.

The complete gate-driven migration snapshot is recorded in the
[2026-08-28 migration audit](gate-driven-migration-20260828.md), including
requirement traceability, regression status and open completion debt.

## Required order

1. Apply `supabase/migrations/202608270001_report_jobs.sql` and
   `202608270002_delivery_receipts.sql` in the intended Supabase project.
2. Confirm the deployed Worker URL and configure `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_DISPATCH_TOKEN`,
   `TELEGRAM_BOT_TOKEN`, `TG_SUBSCRIBERS` and an explicit `ALLOWED_ORIGINS`
   value. Secrets are configured in the provider UI, never committed or
   printed.
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
