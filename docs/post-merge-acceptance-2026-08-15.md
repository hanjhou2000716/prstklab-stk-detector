# Post-merge acceptance evidence (2026-08-15)

This is an evidence record for the merged canonical Creator/news/Railway
stack. It is intentionally separate from the runtime artifacts and does not
claim production acceptance where an external gate is still incomplete.

## Main and local verification

- `origin/main`: `239c72285aec45fd9ce8493e202f4cb2906b8006`
- Merged sequence: #620, #621, #622, #623, #624 (in order)
- Full repository regression: **1246 passed, 1 skipped**
- Ruff: **PASS** (`uv run --locked ruff check src tests`, with a workspace
  cache because the default user cache is ACL-protected)
- Mypy: **PASS** (`uv run --locked mypy src`; 167 source files)
- Python compileall: **PASS** (`src`, `railway-monitor`, `scripts`)
- JavaScript syntax: **PASS** (`node --check site/app.js`)
- Runtime audit: `ok=true`, with explicit production warnings retained
- Delivery smoke: fail-closed as expected because no local
  `TELEGRAM_CHAT_IDS` was configured; no recipient was contacted

## Public Pages

The public manifest was readable and reported `status=ready`:

- release: `release-957714e850293f39`
- market snapshot: `c7466b534b3d117e`
- research snapshot: `research-8b8ec8f6e5ee51aa`
- event snapshot: `event-f67c25c9f5e6f24d`

All six manifest-declared artifacts returned HTTP 200:
`market.json`, `research-report.json`, `event-ledger.json`,
`source-health.json`, `creator-release.json`, and `creator-insights.json`.
Hash verification remains a release-gate responsibility and must be repeated
after the next data refresh, rather than inferred from HTTP success alone.

## Railway health

The public `/health` endpoint returned HTTP 200 after main deployment:

- monitor: `running`
- Jin10: `healthy`
- classifier mode: `repository-shared`
- classifier source and keyword bundle hashes: present
- GDELT: `failed` with `HTTP_429` (source failure and bounded retry are visible and isolated)
- delivery: `delivered`, with one scoped photo receipt and matching trace
- Gmail: `configuration_missing`
- runtime config: legacy delivery secret present, canonical
  `RAILWAY_STATUS_SHARED_SECRET` name not yet present

The Gmail and GDELT items remain external acceptance debt. The controlled
single-recipient Telegram photo test completed successfully:

- Actions run: `31869223299`
- trace: `photo-smoke-e813b36c301d4d39`
- delivery: `delivered` (1 delivered, 0 failed)
- renderer: `1080x1350`, non-empty card
- Railway receipt: accepted; `receipt_matches_last_outbox=true`

This is scoped acceptance evidence, not a claim that the entire broadcast
recipient list or Gmail ingress is configured.

## Required next acceptance actions

1. Configure the canonical Railway secret variable without exposing its value.
2. Configure and verify Gmail/Pub/Sub ingress for the approved Creator sources.
3. Merge the cross-check provenance fix PR #626, then refresh `data-release`.
4. Re-run the Pages release-gate and public Mini App smoke check after the
   refreshed artifacts are published.
5. Run any additional controlled delivery test only after the new release is
   ready, and retain its receipt IDs.

Rollback is to the previous successful Pages release and the prior Railway
deployment; no production data or secret is changed by this evidence commit.
