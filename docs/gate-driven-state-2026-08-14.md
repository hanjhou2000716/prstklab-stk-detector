# Gate-Driven v3 state reconciliation (2026-08-14)

This is a migration checkpoint for the existing stacked implementation.  It
does not replace or reset earlier P0 work.  Statuses are evidence states, not
claims inferred from branch names or previous comments.

## Snapshot

| Field | Evidence |
|---|---|
| Branch | `feat/safe-data-publishing-contract` |
| HEAD | `6581df4` (`docs(gates): record remote CI evidence at current head`) |
| Recovery checkpoint | `checkpoint/migration-2026-08-14-current3` (pre-task) |
| Tracked worktree | clean at checkpoint creation; historical untracked test artifacts are preserved and not staged |
| Local regression | `1139 passed, 1 skipped` at `a7c602c` (`.tmp-external-full`); evidence-only docs commit follows |
| Static checks | Ruff, Mypy and compileall passed at `a7c602c`; evidence-only docs changes do not alter runtime |
| Remote PR | [#578](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/578), open; required quality/security checks pass for `301fb5b` |

## Current task reconciliation

| Task | State | Evidence / next gate |
|---|---|---|
| Canonical NewsStory/provider contract | LOCKED | `tests/test_news_intelligence.py`, full regression |
| Official TWSE/MOPS/SEC/Fed adapters | NEEDS_REVERIFY | `tests/test_news_feed_adapters.py`; failure and 429 isolation; live feed evidence remains external |
| News release artifact production | LOCKED | `schemas/news-release.schema.json`, `news_snapshot_id`/`news_status` and hash written by `release_manifest`; targeted suite passed |
| News release-gate lineage | LOCKED | 59 targeted release/news/Mini App/delivery-gate tests; mismatched market snapshot fails closed |
| News Mini App browser rendering | NEEDS_REVERIFY | static contract loader is verified locally; real ready Pages browser evidence remains external |
| Railway/Telegram production acceptance | BLOCKED | protected runtime configuration and controlled recipient evidence are external prerequisites |
| FinancialJuice sanitized scheduled ingress | partially_integrated | `src/external_observation_input.py` rejects raw/private transport data; Railway sanitized bundle and live release evidence remain external |

`PASS` is not promoted to `LOCKED` when the required objective evidence is not
available in this checkout.  `LOCKED` is reserved for a task whose local
implementation, required regression, and preservation evidence are all
present; it does not imply that an external production gate has passed.

## Affected requirement traceability

| Requirement | Task | Implementation | Verification | Regression | Status |
|---|---|---|---|---|---|
| REQ-P0-04-DOD-NEWS-01 | Bind News to release | `src/release_manifest.py`, `schemas/release-manifest.schema.json` | 63 targeted; 1133 full regression | mixed-release fixture | LOCKED |
| REQ-P0-05-DOD-NEWS-02 | Verify before notify | `src/release_gate.py` | 63 targeted; 1133 full regression | hash and snapshot mismatch | LOCKED |
| REQ-P0-14-DOD-NEWS-03 | Official source isolation | `src/news_feed_adapters.py`, `src/risk_news.py` | adapter parser/429 tests | one provider failure does not drop others; live endpoint evidence pending | NEEDS_REVERIFY |
| REQ-P0-20-DOD-NEWS-04 | Public UI evidence | `site/app.js` | browser/Pages smoke | release mismatch fallback | NEEDS_REVERIFY |
| REQ-ADD-001-DOD-01 | External intelligence enters canonical briefing only as sanitized observations | `src/external_observation_input.py`, `src/scheduled_delivery.py` | 24 targeted tests; 1139 full regression | raw/private/unknown records rejected; no Pages-path input | LOCKED (local) |
| REQ-ADD-001-DOD-02 | FinancialJuice source health and snapshot lineage remain explicit | `src/external_observation_input.py`, `src/scheduled_delivery.py`, workflow | scheduled snapshot binding test; release gate remains required | missing/rejected input cannot become no-event | NEEDS_REVERIFY (external bundle) |

## Regression ledger

| Regression ID | Introduced by | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|---|
| REG-NEWS-001 | prior release path | News artifact could be hashed but not checked by delivery gate | gate loader enumerated only core/Creator artifacts | `7f1fd60`, 51 targeted tests | CLOSED |
| REG-NEWS-002 | environment | Windows shared temp contains inaccessible historical pytest directories | inherited workspace hygiene | CI and isolated basetemp pass; no product assertion changed | ACCEPTED ENVIRONMENT DEBT |
| REG-MIG-001 | migration overlay | prior state document pointed at `c3f43d7` after later evidence commits | state reconciliation lag | `4b60f06`; 63 targeted and 1133 full regression passed | CLOSED |

## Completion debt ledger

| Debt ID | Description | Resolution / owner | Status |
|---|---|---|---|
| DEBT-NEWS-001 | Live official feed and Pages publication evidence | run controlled release after PR #578 is merged | OPEN EXTERNAL |
| DEBT-NEWS-002 | Railway and Telegram delivery receipt evidence | protected runtime configuration; single-recipient dry-run | OPEN EXTERNAL |
| DEBT-NEWS-003 | Historical untracked test/temp artifacts | separate workspace hygiene task; do not stage during feature work | OPEN NON-PRODUCTION |
| DEBT-MIG-001 | Re-run required verification at migration HEAD | `63 passed, 1 skipped`; `1133 passed, 1 skipped`; Ruff/Mypy/compile/node checks | CLOSED |
| DEBT-FJ-001 | Railway has not yet supplied a live sanitized FinancialJuice bundle to the scheduled workflow | configure `EXTERNAL_OBSERVATIONS_PATH` with reviewed derived JSON; run release-gated workflow | OPEN EXTERNAL |

### Migration audit update (2026-08-14, multi-market News release binding)

- `news.json` now publishes one release-bound envelope containing Taiwan and US
  News Intelligence views when both are present; legacy single-market payloads
  remain readable.
- The release gate validates each market payload and its shared provider
  registry. The Mini App verifies the News artifact hash, market snapshot and
  News snapshot before rendering either tab, including last-good fallback.
- Targeted release/news/Mini App/delivery-gate suite: `63 passed, 1 skipped`; full local regression: `1133 passed,
  1 skipped`; Ruff, Mypy, compile and `node --check` pass.
- PR [#578](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/578)
  required checks pass for `301fb5b` (test-and-dry-run, CodeQL, dependency review,
  SBOM and duplicate CodeQL check). Pages/Railway/Telegram production acceptance remains
  external and fail-closed.

### Migration audit update (2026-08-14, sanitized external ingress)

- `EXTERNAL_OBSERVATIONS_PATH` is now an opt-in scheduled-workflow input. The
  loader accepts only `public_safe` FinancialJuice-derived records with stable
  observation IDs, rejects raw mail/Gmail transport identifiers/private fields,
  and never reads from the Pages tree.
- Accepted rows are attached to the same market snapshot and briefing consumed
  by the existing intelligence pipeline. Rejected/missing input is represented
  by an optional source-health row; it cannot be interpreted as a clean scan or
  independently trigger a high-risk alert.
- Targeted ingress/scheduled/workflow suite: `24 passed`; full local regression:
  `1139 passed, 1 skipped`; Ruff, Mypy and compileall pass.
- This closes the local canonical integration gap only. A Railway-provided
  sanitized bundle, ready release and controlled Telegram receipt are still
  external evidence gates and remain fail-closed.

## Gate decision

The canonical News release-lineage task and this migration verification are
`LOCKED` on this branch.  Do not merge solely
from local evidence while PR checks are pending.  Pages browser and protected
Railway/Telegram acceptance remain external gates; no production side effect
is attempted by this checkpoint.
