# Zero-cost production migration

This repository now contains the first, offline-verifiable slice of the
Railway removal plan. Heavy Python market and research computation remains in
GitHub Actions; the browser boundary is designed for Cloudflare Worker and
the durable job/report contract is designed for Supabase PostgreSQL.

## Runtime boundaries

| Concern | Runtime | Contract |
| --- | --- | --- |
| Market downloads, news and strategy scans | GitHub Actions | `jobs/process_report_job.py` |
| Job/report persistence | Supabase PostgreSQL | `supabase/migrations/202608270001_report_jobs.sql` |
| Auth, validation, dispatch, health and Telegram proxy | Cloudflare Worker | `worker/src/index.ts` |
| Mini App UI and async polling | Cloudflare Pages | `site/report-client.js` |
| Gmail Watch lease and private cursor | Supabase PostgreSQL + GitHub Actions | `supabase/migrations/202608300001_gmail_zero_cost_ingress.sql`, `.github/workflows/gmail-watch-renew.yml` |
| Gmail Pub/Sub ingress | Cloudflare Worker → GitHub Actions | `/api/gmail-pubsub`, `.github/workflows/gmail-history-sync.yml` |

The service-role key, GitHub dispatch token and Telegram token never belong in
the Pages bundle. The Worker verifies Telegram WebApp `initData`; a frontend
`user_id` is not accepted as identity. `ALLOWED_ORIGINS` must be an explicit
comma-separated allowlist, never a wildcard.

## Setup order

1. Apply the Supabase migration from `supabase/migrations/`.
2. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` as GitHub Actions and
   Worker secrets. Add a least-privilege `GITHUB_DISPATCH_TOKEN` that can
   dispatch the report workflow for this repository.
3. Configure the Worker variables `GITHUB_REPOSITORY`, `TG_ALLOWED_USERS`,
   `TG_SUBSCRIBERS` (or `TELEGRAM_CHAT_IDS`) and explicit `ALLOWED_ORIGINS`.
   Store the bot credential as `TELEGRAM_BOT_TOKEN`; the Worker also accepts
   legacy `TG_TOKEN` during migration, but new deployments should use the
   canonical name shared with GitHub Actions.
4. Deploy `worker/` with Wrangler, then set the Pages build-time
   `PUBLIC_API_BASE_URL`/`PRSTK_API_BASE_URL` to the Worker URL.
5. Set Worker `GMAIL_PUBSUB_AUDIENCE` to the exact Pub/Sub push audience and
   `GMAIL_PUBSUB_SERVICE_ACCOUNT` to the exact OIDC service-account email.
   Configure the Pub/Sub push URL as `https://<worker>/api/gmail-pubsub`.
   Add the Gmail OAuth secrets and non-secret Watch variables to GitHub Actions.
6. Set the Actions variable `PUBLIC_OBSERVATIONS_URL` to the Worker
   `/external-observations` endpoint. It must expose only reviewed,
   public-safe observations.
7. Keep the legacy Railway service available until the external acceptance
   checklist passes. This change does not silently cut over production.

## Async contract

`POST /api/report` validates `tw`/`us`, creates a queued job, dispatches
`.github/workflows/report-worker.yml`, and returns HTTP 202 with `job_id`.
The Actions worker closes every job as `completed` or `failed`; a retry never
overwrites a terminal state. The Mini App polls for up to five minutes and
keeps the job visible after timeout. `POST /api/send` accepts only a generated
report and sends it through the Worker; it does not run heavy computation.

## Verification and rollback

Run the offline contract tests with an isolated pytest directory so temporary
files outside the repository cannot be collected:

```text
python -m pytest -q --basetemp=.pytest-basetemp-migration
```

Before cutover, verify a real Supabase job, a successful Watch renewal, a
signed Pub/Sub notification, a successful history sync, Worker health, Pages
polling and one explicitly authorised Telegram canary. If any gate fails, stop
dispatching new jobs, restore the previous Pages release and continue using
the legacy Railway monitor as rollback. Do not delete Railway data until the
external acceptance evidence is archived.

See [migration inventory](migration-inventory.md) for the current overlap and
the remaining operator-only gates.
