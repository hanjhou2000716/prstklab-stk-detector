## Gmail Watch automatic renewal and acceptance health

Depends on the merged external-acceptance checkpoint (#712) and continues the
canonical Railway Gmail ingress path.

### Changes

- Adds a bounded official Gmail OAuth refresh-token → `users.watch` renewal
  adapter. Durable state stores only `historyId` and watch expiration.
- Runs renewal inside the monitor loop without allowing OAuth/provider failures
  to stop Jin10, GDELT, or delivery polling.
- Reads OAuth settings from Railway variables without exposing values in health,
  receipts, logs, or error payloads.
- Separates configured Gmail ingress from the operational watch lease in
  external acceptance (`railway_gmail_watch:<status>`).
- Binds Creator correlation freshness to the immutable release snapshot so
  historical releases are not incorrectly marked stale by the rebuild clock.
- Documents required variables, fail-closed behavior, and rollback.

### Verification

- `uv run ruff check src tests` — pass.
- `uv run mypy src` — pass (177 source files).
- Targeted Gmail/acceptance/correlation tests — 29 passed.
- Full pytest — 1356 passed, 2 skipped.
- `python -m compileall -q src railway-monitor` — pass.
- `node --check site/app.js` — pass.
- `python -m scripts.verify_canonical_overlap` — pass, 0 drift.
- `uv run python -m src.production_e2e` — pass; offline, no secrets or
  production side effects; card 1080×1350 and mocked Telegram delivery pass.

### External acceptance status

The last read-only public acceptance remains `NEEDS_REVERIFY`: Pages is ready
and Railway is reachable, while the deployed service still reports GDELT
`invalid_json` and Gmail `watch_status=failed`/HTTP 403. This PR fixes the
renewal path and reporting contract; Google Pub/Sub/Gmail permissions and the
deployed Railway variables must be corrected before a production acceptance
run can become PASS.

### Rollback

Revert this PR and redeploy the previous Railway release. Existing Gmail push
ingress, Jin10/GDELT polling, release gates, and delivery receipts remain
independent; no public data is deleted.
