# Gate-Driven migration snapshot — 2026-08-15

This is the authoritative snapshot for the current continuation. It records
repository evidence only; it does not promote a green pull request into live
Railway, Pages, Telegram, or Gmail acceptance.

## Recovery checkpoint

| Item | Evidence |
|---|---|
| Branch | `feat/REQ-ADD-045-classifier-health-provenance` |
| Base | `main` |
| HEAD | `a6045fa30a7a2842219166f776f0ce607f6d7aba` |
| Recovery point | `a6045fa docs(P0-14): record classifier health CI evidence` |
| PR | [#624](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/624) |
| PR state | open, non-draft, mergeable; not merged by this task |
| Tracked working tree | clean |
| Untracked state | `.pytest-remote-cov/` exists but is inaccessible to this workspace; never staged or deleted |

The checkpoint is an atomic documentation commit. No merge, release, deploy,
force-push, production notification, or data deletion was performed.

## Current task reconciliation

| Task | Scope | Status | Evidence |
|---|---|---|---|
| REQ-ADD-044 | package the canonical classifier for root-only Railway images | PASS / LOCKED | targeted 103 passed; full 1245 passed, 1 skipped; PR #623 CI passed |
| REQ-ADD-045 | expose classifier and keyword-bundle provenance in Railway health | PASS / LOCKED | targeted 104 passed; full 1246 passed, 1 skipped; Ruff, Mypy, compileall, generator drift check passed; PR #624 CI passed |
| Migration audit | reconcile current state and external gates | IN_PROGRESS | this snapshot; external acceptance remains separate below |

## Verification evidence

- Targeted Railway/classifier/Gmail suite: **104 passed**.
- Repository regression: **1246 passed, 1 skipped**.
- `uv run ruff check src tests`: passed.
- `uv run mypy src`: passed (`167` source files).
- Python compilation and generated Railway bundle `--check`: passed.
- Runtime audit and offline system dry-run: passed.
- PR #624 quality/dry-run: run `31856904114`, job `94943293353`, passed.
- PR #624 security: run `31856904104`, CodeQL/dependency-review/SBOM passed.
- Separate CodeQL: run `94943405591`, passed.

## Requirement state summary

The canonical P0 registry remains `docs/p0-requirement-traceability-2026-08-15.md`.
At this snapshot, its 29 P0 rows are classified as:

- **19 PASS** for repository contracts with local/CI evidence.
- **10 NEEDS_REVERIFY** for live delivery, browser, source freshness, Railway,
  or point-in-time production evidence.
- No row is treated as PASS solely because code exists or a PR is mergeable.

## Regression ledger

| ID | Symptom / risk | Root cause or required proof | Status |
|---|---|---|---|
| REG-MIG-001 | Inaccessible `.pytest-remote-cov/` can hide local cleanup state | OneDrive/filesystem ACL; do not force-delete or stage | OPEN / ENVIRONMENT |
| REG-EXT-001 | Railway Creator/FJ ingress and receipt not proven live | Controlled Railway run with sanitized bundle | OPEN / EXTERNAL |
| REG-EXT-003 | Telegram production photo/deep-link/receipt not proven | One approved recipient only | OPEN / EXTERNAL |
| DEBT-NEWS-001 | Official feed freshness and market split live evidence missing | Capture TWSE/MOPS/SEC/Fed source-health evidence | OPEN / EXTERNAL |
| DEBT-FJ-001 | FinancialJuice sanitized runtime bundle not observed in Railway | Configure reviewed bundle and capture release evidence | OPEN / EXTERNAL |
| DEBT-CREATOR-001 | Late Creator delivery/photo receipt not proven | Controlled single-recipient retry/dedupe test | OPEN / EXTERNAL |

## Preservation contracts

PC-001 through PC-008 remain protected: market and research pipelines,
release-gate ordering, Mini App routing, Telegram isolation/deduplication,
Railway health/auth semantics, Gmail privacy, Pages behavior, and no-trade/no-
secret constraints. Any future change touching a locked boundary must reopen
the affected task, rerun its original tests, then run impact regression before
locking it again.

## Next gate

The next safe continuation is to keep local implementation and evidence work
separate from live acceptance. PR #624 may be reviewed/merged by the user only
after the stacked dependency order is confirmed. Live Railway, Pages, Mini App,
Telegram, and Gmail checks remain `NEEDS_REVERIFY`; no production result is
inferred from these local and CI passes.
