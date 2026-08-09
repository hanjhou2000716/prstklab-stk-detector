# Production system-test gate

Run this gate only after the reconciliation and repair PRs are merged into
`main` and the merge commits have been verified as ancestors of `origin/main`.

```powershell
uv lock --check
uv sync --locked --all-groups
uv run ruff check src tests
uv run pytest -q
python -m compileall -q src railway-monitor
node --check site/app.js
python -m src.runtime_audit
python -m src.system_dry_run
```

Then dispatch the Pages/research workflow, verify a `status=ready` manifest and
matching artifact hashes, and run the Telegram dry-run with a single test chat
ID. Formal photo delivery is one release-gated `sendPhoto` message containing
all three parts in the same Telegram message:

1. a caption no longer than 40 Unicode characters above the media;
2. one readable 1080x1350 PNG card; and
3. one release-scoped Mini App button below the media.

The scheduled text-only path remains available only for legacy compatibility;
new production photo paths must pass the renderer and release gate first. A
missing Playwright/Chromium runtime, invalid PNG, manifest mismatch, or failed
public release verification blocks the photo and records `renderer_error_type`
or the gate reason in the delivery receipt. It must never send a blank fallback
image. The explicitly scoped `photo_test` workflow is the authoritative live
renderer check and is limited to one test chat ID.

For a live photo smoke test, verify all of the following from the workflow
outputs and Railway receipt before considering it successful:

```text
photo_card_dimensions=1080x1350
photo_delivery_delivered=1
photo_delivery_failed=0
receipt_status=delivered
receipt.release_id == manifest.release_id
receipt.snapshot_id == manifest.market_snapshot_id (or alert snapshot)
```

If the renderer or release gate fails, keep the previous `status=ready`
release active and do not retry by broadcasting to the production recipient
list. Re-run only after the failure is corrected.

Rollback is release-based: keep the last verified manifest and data-release
commit, then re-run the Pages deployment without deleting release history.
