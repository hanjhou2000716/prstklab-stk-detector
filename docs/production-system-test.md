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
ID. After PR #346 is merged, production scheduled delivery uses one validated
`sendPhoto` message: a caption of at most 40 Unicode characters, a readable
1080x1350 PNG, and a release-scoped Mini App button. Renderer failure is
fail-closed and records a delivery receipt instead of sending a blank card.
Before merging PR #346, use the explicitly scoped photo smoke test only.

Rollback is release-based: keep the last verified manifest and data-release
commit, then re-run the Pages deployment without deleting release history.
