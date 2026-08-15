# Gate-Driven migration snapshot — 2026-08-15

This is the authoritative snapshot for the current continuation. It records
repository evidence only; it does not promote a green pull request into live
Railway, Pages, Telegram, or Gmail acceptance.

## Recovery checkpoint

| Item | Evidence |
|---|---|
| Branch | `feat/REQ-ADD-045-classifier-health-provenance` |
| Base | `main` |
| HEAD | `ac70eefc07c81219810d990e03c4e79a0fb6cf84` |
| Recovery point | `ac70eef docs: record Railway and Pages external gate evidence` |
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

Post-checkpoint local gate rerun:

- Traceability, Railway monitor, and classifier regression: **95 passed**.
- `python -m src.runtime_audit`: `ok=true`; warnings remain for six market
  source gaps, a building research source, and missing/not-ready production
  event/research snapshots. These warnings are intentionally not relabeled as
  success.
- `python -m src.delivery_smoke_test`: fail-closed with
  `TELEGRAM_CHAT_IDS is empty`; no production notification was sent.
- `compileall` for `src`, `railway-monitor`, and `scripts`, plus
  `node --check site/app.js`: passed.

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

## Migration gate rerun after overlap matrix checkpoint

- Atomic audit commit: `57b76b9` (`docs: reconcile canonical intelligence ownership`).
- Canonical Creator/FJ/news/release/Telegram overlap suite: **253 passed**.
- Full repository regression: **1246 passed, 1 skipped**.
- `ruff check src tests`: **PASS**; `mypy src`: **PASS**; compile check: **PASS**.
- Runtime audit remains `ok=true` with only the previously documented source,
  research-building and production-artifact warnings.
- Delivery smoke remains intentionally fail-closed (`TELEGRAM_CHAT_IDS` is
  empty), so no real recipient was contacted.

## External gate capture (read-only, 2026-08-15)

- Railway `/health` returned HTTP 200 with a running monitor and healthy Jin10
  poller. The live deployment was still based on PR #619 and reported
  `classifier_mode=standalone-bundled`; PR #624 has not been promoted to that
  service yet.
- The same response reported GDELT `HTTP_429` and health callback
  `HTTP_403`, with bounded retry metadata. These remain external configuration
  or rate-limit debts and are not relabeled as source success.
- Railway delivery was `not_checked` with no receipt trace. Gmail/Creator
  ingress was `configuration_missing`; no production Telegram delivery was
  attempted.
- Public Pages manifest was readable and `status=ready` for release
  `release-957714e850293f39` (created 2026-08-13). All six declared artifacts
  matched their manifest SHA-256 hashes. This is an integrity PASS for that
  release, while freshness and post-merge publication remain
  `NEEDS_REVERIFY`.

These observations update the external debt ledger; they do not close it.

The post-evidence PR checks are also green: quality/dry-run run
`31859330412`, security run `31859330400`, and separate CodeQL check
`94949854964`.
