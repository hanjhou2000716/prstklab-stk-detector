# PRStK Railway removal migration inventory

Snapshot date: 2026-08-27 (Asia/Taipei)  
Baseline: `123395ee` (`origin/main`)  
Working branch: `feat/railway-removal-zero-cost`

This inventory is the migration checkpoint. It records the repository state and
the replacement contracts now present on the feature branch; it is not a claim
that the external cutover has already happened.

The machine-readable requirement/evidence ledger is
[`docs/traceability.json`](traceability.json), validated by
[`src/traceability.py`](../src/traceability.py).  A `PASS` entry requires
objective evidence; provider-side work without captured evidence remains
`NEEDS_REVERIFY` or `BLOCKED`.

| Current component | Current file(s) | Current responsibility | Target component | Migration status |
| --- | --- | --- | --- | --- |
| Public Mini App | `site/index.html`, `site/app.js`, `site/styles.css`, `site/report-client.js` | Static release dashboard, authenticated async report polling and Telegram WebView | Cloudflare Pages | partially migrated |
| Market/report engine | `src/market_data.py`, `src/briefing_cards.py`, `src/scheduled_delivery.py`, `jobs/process_report_job.py` | Heavy Python collection, normalization and release production | GitHub Actions report worker | partially_integrated |
| Scheduled reports | `.github/workflows/scheduled-brief.yml` and research workflows | Scheduled Python refresh, Pages publish and optional notification | GitHub Actions | production (legacy Railway callback remains optional) |
| Railway event ingress | `railway-monitor/app.py` and sibling modules | Gmail/Jin10 polling, source health and repository dispatch | Cloudflare Worker API + provider-specific Actions jobs | legacy; cutover pending |
| Async report API | `worker/src/index.ts` | Auth, validation, job enqueue/status, workflow dispatch, Telegram proxy and health | Cloudflare Worker | partially_integrated |
| Telegram transport | `src/telegram_client.py`, `src/creator_notification.py` | Release-gated text/photo delivery and receipts | Cloudflare Worker `/api/send` for interactive reports; Actions for scheduled delivery | production + target adapter pending |
| Alert decision boundary | `src/alert_contract.py`, `src/alert_lifecycle.py`, `src/alert_budget.py`, `src/alert_orchestrator.py` | Shared envelope, lifecycle, material-change and budget decision | All new async report/event consumers | partially_integrated |
| Alert card renderer | `src/alert_card_renderer.py`, `src/photo_smoke_test.py` | Fixed-size evidence card with fail-closed renderer validation | Telegram photo delivery and offline acceptance | production |
| Persistence | `site/data/*`, `data-release`, Railway SQLite, `app/db/repository.py` | Immutable public release plus monitor state | Supabase PostgreSQL for jobs/reports/status; data-release remains public snapshot | partially_integrated |
| Release gate | `src/release_gate.py`, `src/pages_release.py` | Validate immutable artifacts before notification | Actions publish gate and Pages deployment | production |
| Research strategies | `src/*research*.py`, `src/run_*.py` | Heavy scans and explainability artifacts | GitHub Actions only | production |
| Secrets | GitHub Secrets, local `.env`, Railway Variables | Runtime credentials | GitHub Secrets + Cloudflare Secrets + Supabase service role | migration pending external setup |

## Confirmed entrypoints

- Scheduled market data is produced by `python -m src.scheduled_delivery`.
- The existing Railway service entrypoint is `railway-monitor/app.py`.
- The public dashboard is the `site/` Pages artifact; there is no separate
  `web/` application in the current main branch.
- Heavy computation is Python and must remain outside a Cloudflare Worker.

## Preservation boundary

The migration keeps the current static release and scheduled workflows intact
until the replacement path has passed its own smoke tests. No Railway service,
database, branch or public release is deleted by this checkpoint.

## External acceptance still required

The following require credentials or a provider-side action and therefore cannot
be proven by offline CI alone:

1. Provision a Supabase project and apply the migration.
2. Deploy a Cloudflare Worker and configure its secrets/allowed origins.
3. Deploy the Pages API base URL and exercise a real authenticated job.
4. Rotate or confirm production Telegram credentials before canary delivery.
5. Turn off Railway only after the new ingress and scheduled paths pass a
   controlled single-recipient acceptance test.

Until those checks are captured, the migration status is **IN_PROGRESS**.
