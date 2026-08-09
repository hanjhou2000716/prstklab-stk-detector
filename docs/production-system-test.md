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
ID. Production scheduled delivery must use text `sendMessage`; the photo
renderer is only exercised by the explicitly scoped photo smoke test.

Rollback is release-based: keep the last verified manifest and data-release
commit, then re-run the Pages deployment without deleting release history.
