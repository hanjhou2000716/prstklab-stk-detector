# Post-merge validation — 2026-08-09

This record documents the checks run against `origin/main` after the photo
delivery stack was merged. It is evidence for the release process, not a
replacement for the production runbook.

## Main and public release

- Main HEAD: `97894eaa6eced93ff6771cb3d56486afd0846f46`.
- Public manifest: `status=ready`, release
  `release-d9ca5e04b57bf22b`.
- Market/research/event snapshots are
  `3a9a356d1a2a1688`, `research-05c7ae8487b01350`, and
  `event-aef6826d45327217`.
- The published SHA-256 values for all three artifacts match the manifest.

## Offline quality gates

- `uv lock --check` and `uv sync --locked --all-groups`: passed.
- `uv run ruff check src tests`: passed.
- `uv run mypy src`: passed with zero errors after the P7 typing cleanup.
- `uv run pytest -q --cov=src --cov-fail-under=80`: 610 passed, 80.20%.
- `python -m compileall -q src railway-monitor` and `node --check site/app.js`:
  passed.
- Runtime audit, release-gate tests, callback tests and photo contract tests:
  passed.

## Scoped Telegram photo E2E

Actions run [31293379120](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/31293379120)
was dispatched with `photo_test=true` and the explicit test recipient only.
The job reported:

- `photo_card_dimensions=1080x1350`
- `photo_delivery_delivered=1`
- `photo_delivery_failed=0`

The test path is fail-closed: renderer or release-gate failure blocks delivery
instead of sending a blank diagnostic image. The workflow does not fall back to
the production broadcast list.

## Remaining operational boundary

The live Railway delivery-receipt endpoint was not configured in this checkout,
so callback tests are mocked/offline. Configure the Railway status URL and
shared secret before treating a live receipt as verified. The deprecated
singular `TELEGRAM_CHAT_ID` secret should be removed or rotated after confirming
that `TELEGRAM_CHAT_IDS` is the only production recipient variable; its value is
never printed by the tooling.
