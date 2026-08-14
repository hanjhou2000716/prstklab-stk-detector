# Gate-Driven v3 migration checkpoint — 2026-08-15

This is the authoritative reconciliation snapshot for the in-flight upgrade.
It is intentionally separate from older gate notes written before the latest
main release and does not promote historical claims to `PASS` without current
evidence.

## Repository snapshot

| Item | Evidence |
|---|---|
| Remote main at audit start | `587a27b155b92e9614fa5485d632fde28c087a64` |
| Audit branch base | `main` (origin/main `587a27b155b92e9614fa5485d632fde28c087a64`) |
| Current audit branch | `feat/REQ-ADD-039-gate-migration-audit` |
| Evidence code checkpoint | `2d523b8` (`docs: capture current Railway external gate status`) |
| Working tree | Clean at the snapshot; no uncommitted or untracked product changes. |
| Historical stack observed | PRs #566–#617 are already ancestors of current `main`; they are historical context, not an outstanding merge queue. |

Local full-regression evidence at this checkpoint: `python -m pytest -q
--basetemp=.pytest-full` completed with **1231 passed, 1 skipped** in 50.55s.
The workspace basetemp was removed after the run; no production data or
notification was touched.

## Requirement traceability (migration scope)

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| P0-09 / P0-12 | REQ-ADD-039-T01 | Railway Gmail parses a bounded public-safe observation projection | `tests/test_railway_gmail_gateway.py` | 17 targeted tests pass; no raw body/sender/transport IDs in projection | duplicate and DLQ tests pass | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T02 | Authenticated `/external-observations` export and client | `tests/test_railway_observation_client.py` | signature, status, schema and private-field rejection tests pass | missing config remains fail-closed | PASS |
| P0-09 / P0-12 | REQ-ADD-039-T03 | Scheduled delivery merges Railway and reviewed local observations | `tests/test_scheduled_delivery.py` plus external-input tests | 27 targeted/regression tests pass | local reviewed input remains usable when Railway is unavailable | PASS |
| P0-24 / P0-29 | REQ-ADD-039-T04 | Gate-driven evidence and debt ledgers | this document and canonical `docs/p0-requirement-traceability.md` | PR #618 at HEAD `2d523b8`: quality run `31845113369` and security run `31845113354` passed (CodeQL, dependency review, SBOM, full test-and-dry-run) | no merge performed; scoped photo smoke is recorded below | PASS / LOCKED |

`PASS` above is limited to the listed implementation and tests. It is not a
claim that the entire product or all original P0 DoDs are complete.

The full P0-01..P0-29 requirement index and its current external-gate debt are
maintained in the canonical `docs/p0-requirement-traceability.md` registry and
covered by `tests/test_p0_traceability_registry.py`; this checkpoint does not
create a second registry.

## Integration matrix (current evidence)

| Module | Files exist | Tests | Formal pipeline | JSON | Mini App | Telegram | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Source adapters / market snapshot | yes | yes | yes | yes | yes | yes | production |
| Release manifest / release gate | yes | yes | yes | yes | yes | yes | production |
| Alert lifecycle / budget / dedup | yes | yes | yes | yes | yes | yes | production |
| Telegram delivery receipts | yes | yes | yes | yes | n/a | yes | production |
| Mini App deep links / release fallback | yes | yes | yes | yes | yes | n/a | production |
| Creator / FinancialJuice registry | yes | yes | partial | partial | partial | partial | partially_integrated |
| Railway Gmail → sanitized public observation export | yes | yes | this PR | this PR | pending deploy | pending acceptance | partially_integrated |
| Event clustering / impact graph | yes | yes | partial | partial | partial | partial | partially_integrated |
| Macro surprise / regime / contagion | yes | yes | partial | partial | partial | partial | partially_integrated |
| Strategy registry / point-in-time backtest | yes | yes | partial | partial | partial | n/a | partially_integrated |
| Private portfolio risk | yes | yes | no public pipeline | no public output | isolated | no | experimental |
| Advice gate / paper portfolio | yes | yes | partial | partial | partial | no trade action | experimental |

## Regression ledger

| ID | Symptom | Root cause / mitigation | Evidence | Status |
|---|---|---|---|---|
| REG-039-01 | OneDrive can intermittently fail raw-observation temp-file replacement | Environment/filesystem behavior; rerun on CI/Linux or a local non-synced checkout | prior baseline runs, not reproduced by targeted tests | OPEN / needs reverify |
| REG-039-02 | Railway export unavailable when URL/secret are absent | Client returns `configuration_missing`; local reviewed input remains valid and no alert is invented | client test | CLOSED |
| REG-039-03 | Invalid/private Gmail-derived row could enter release | Sanitized allowlist and SQLite privacy boundary reject it | ingress + external-input tests | CLOSED |

## Current external evidence

The following evidence was captured after the migration checkpoint and is
explicitly scoped; it does not claim a complete production acceptance:

- Public Pages manifest: `release-957714e850293f39`, `status=ready`; all six
  declared artifact hashes (`market`, `research`, `event`, `source-health`,
  `creator-release`, `creator-insights`) matched the public bytes.
- Railway `/health`: monitor `running/healthy`; GDELT remains rate-limited
  (`HTTP_429`) and GitHub dispatch remains permission-denied (`HTTP_403`), so
  those are open runtime configuration issues rather than hidden successes.
- Scoped photo smoke: Actions run `31839093636`, job `94891873503`, one
  recipient only; Railway receipt projected `delivered`, `delivered_count=1`,
  `failed_count=0`, `recipient_count=1`, `receipt_matches=true`, trace
  `photo-smoke-b09bb97240c54a9f`.
- No broadcast, merge, or user-visual confirmation of the Mini App WebView
  was performed in this checkpoint.

### Post-checkpoint reconciliation evidence

- Overlap audit commits: `c94fcee`, `2d523b8` on PR #618.
- Latest quality run: `31840194185` (success); latest security run:
  `31840194207` (success, including CodeQL, dependency review and SBOM).
- Public Creator release remains `ready` with one sanitized insight; public
  source-health exposes Creator provider rows. FinancialJuice remains optional
  and has no public row until its sanitized Railway bundle is configured.
- The current live Railway projection still reports GDELT `HTTP_429` and
  dispatch callback `HTTP_403`; these are explicitly open external gates.

- Mini App loader preference fix (`a09bb30`) now selects the bounded public
  Creator insight projection before the internal envelope. Targeted UI and
  fallback tests: `4 passed`; latest PR quality run `31841614424` and security
  run `31841613208` passed.

## Completion-debt ledger

| Debt ID | Description | Resolution / next gate | Status |
|---|---|---|---|
| DEBT-039-01 | Ruff is not installed in this local runtime | Remote CI Ruff gate passed; local environment remains unable to reproduce it without network/cache access | CLOSED (CI evidence) |
| DEBT-039-02 | Railway GDELT 429 and GitHub dispatch 403 remain live runtime configuration issues; Mini App WebView visual acceptance is pending | Fix provider rate-limit/backoff configuration and protected dispatch permission; then perform post-merge acceptance | OPEN / external |
| DEBT-039-03 | Full repository regression and all original P0 DoDs not rerun on this checkpoint | Local full regression is 1231 passed / 1 skipped; rerun on latest main and update traceability evidence | OPEN |
| DEBT-039-04 | Existing older gate notes contain PASS claims predating this snapshot | Treat this document as current authority; reverify each mapped DoD | OPEN |

## Preservation contracts

- **PC-001** market/risk/research pipelines remain unchanged unless they consume
  the new optional observation projection.
- **PC-002** release gate and stale/fail-closed rules remain mandatory; no
  Railway failure can create a qualifying alert.
- **PC-003** Telegram delivery remains release-bound and single-recipient
  testing only; this checkpoint performs no production broadcast.
- **PC-004** raw Gmail body, sender, attachment and transport identifiers never
  enter public artifacts.
- **PC-005** local reviewed `EXTERNAL_OBSERVATIONS_PATH` remains a safe fallback
  when Railway is unavailable.

## Recovery / rollback

The branch is a recoverable checkpoint based on the latest audited `main`
(`587a27b155b92e9614fa5485d632fde28c087a64`). Rollback is a PR revert (or branch deletion before merge);
it removes the Railway export path while leaving prior release and Telegram
gates intact.
No merge, deploy, release publication, or production notification is part of
this checkpoint.
## Migration snapshot: 2026-08-15 continuation

- Branch: `feat/REQ-ADD-039-gate-migration-audit`
- HEAD: `2d523b8`
- `origin/main`: `587a27b155b92e9614fa5485d632fde28c087a64`
- Working tree: clean before this evidence update.
- Recovery checkpoint: the previous `2d523b8` commit is the rollback point for this continuation; no reset or force-push is required.

### Reconciled state

| Area | Status | Evidence |
|---|---|---|
| Creator public artifact precedence | PASS | `site/app.js`, `tests/test_creator_insight_ui_contract.py`; 4 targeted tests and `node --check site/app.js` |
| Public release manifest/hash binding | PASS | live Pages manifest `release-957714e850293f39`; six artifact SHA-256 checks matched |
| Full local regression | PASS | `python -m pytest -q --basetemp=.pytest-final`: 1231 passed, 1 skipped |
| Runtime audit | NEEDS_REVERIFY | `python -m src.runtime_audit` is structurally valid but reports local checked-in data gaps |
| Railway/GDELT | NEEDS_REVERIFY | Railway health is running; GDELT is bounded at HTTP 429 and health callback is HTTP 403 |
| Telegram photo delivery | NEEDS_REVERIFY | scoped one-recipient photo smoke previously delivered with matching receipt; no current broadcast was sent |
| Gmail ingress | BLOCKED | Railway reports `configuration_missing`; OAuth/PubSub credentials are not available in this workspace |

### Stale PR overlap

PRs whose heads are already ancestors of `origin/main` are superseded, not additional production pipelines. They may be closed without deleting branches after posting the superseded explanation. PR #546 and #554 require file-level reconciliation because their heads are not local ancestors, but all their implementation paths are present on `origin/main` under later commits (`71c1441`, `f9b9683`, `87058ef`, `d7857c6`).

The overlap cleanup closed the verified stale set #545, #546, #549–#554 and
#566–#576. Remaining older stacked PRs are intentionally not mass-closed by
this checkpoint until each head is individually compared with `origin/main`.
This avoids treating an unverified branch as superseded. The canonical active
continuation remains PR #618.

### Completed individual overlap audit

The remaining stacked Creator, external-intelligence, source-health, strategy,
news and release PRs were subsequently checked one by one. Their heads were
ancestors of `origin/main`, or their exact behavior was present in later
mainline commits; they were closed as superseded without deleting branches:

`#479–#482`, `#486–#493`, `#496–#516`, `#520–#522`, `#527–#533`,
`#543–#554`, and `#566–#576` (with gaps representing PRs that were not open).

The only remaining open PR in the repository is the canonical continuation
`#618`. This cleanup changed no source or release data and does not constitute
mainline merge or production acceptance.

### Latest Railway health capture

The live `/health` endpoint remains reachable and the monitor heartbeat is
healthy. It currently reports Jin10 healthy, delivery receipt consistency for
the scoped photo smoke, GDELT `HTTP_429` with bounded fallback disabled for the
current cycle, and the health callback `HTTP_403`. Gmail remains
`configuration_missing`; no credentials or private payloads were read. These
states remain external acceptance debt and are intentionally not promoted to
PASS by a local test.

Post-checkpoint regression: `python -m pytest -q --basetemp=.pytest-final`
returned `1231 passed, 1 skipped`; the temporary directory was removed and the
working tree is clean. PR #618 CI is green (quality/dry-run, CodeQL,
dependency-review and SBOM).

### Gate v3 continuation verification — 2026-08-15

- Snapshot rechecked on HEAD `2d523b8`; working tree was clean before this
  documentation update and `origin/main` remains `587a27b155b92e9614fa5485d632fde28c087a64`.
- Full repository regression: `python -m pytest -q --basetemp=.pytest-migration`
  returned **1231 passed, 1 skipped**; the temporary directory was removed.
- JavaScript syntax: `node --check site/app.js` passed.
- Runtime audit returned `ok=true` with explicit warnings for checked-in
  market gaps, building research, and missing local event/research/ready
  manifest artifacts. These warnings are not promoted to production PASS.
- Delivery dry-run returned `ok=true`, one synthetic recipient, HTTPS dashboard,
  configured callback, and no errors; no Telegram API was called.

The only current open PR remains #618. This evidence update does not merge,
deploy, publish, or send a production notification. Production acceptance is
still **INCOMPLETE** until the external Railway permissions/configuration and
post-merge Pages/Mini App checks are reverified.
