# Gate-Driven v3 state reconciliation (2026-08-14)

This is a migration checkpoint for the existing stacked implementation.  It
does not replace or reset earlier P0 work.  Statuses are evidence states, not
claims inferred from branch names or previous comments.

## Snapshot

| Field | Evidence |
|---|---|
| Branch | `feat/safe-data-publishing-contract` |
| HEAD | `7f1fd60ba2859747876f8767919b4f53032581cd` |
| Recovery checkpoint | `checkpoint/migration-2026-08-14-current` |
| Tracked worktree | clean at checkpoint creation; historical untracked test artifacts are preserved and not staged |
| Local regression | `1129 passed, 1 skipped` |
| Static checks | Ruff, Mypy, compileall and `node --check site/app.js` passed |
| Remote PR | [#577](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/577), open; latest quality/security checks were still running at snapshot time |

## Current task reconciliation

| Task | State | Evidence / next gate |
|---|---|---|
| Canonical NewsStory/provider contract | LOCKED | `tests/test_news_intelligence.py`, full regression |
| Official TWSE/MOPS/SEC/Fed adapters | PASS | `tests/test_news_feed_adapters.py`; failure and 429 isolation |
| News release artifact production | PASS | `news_snapshot_id`/`news_status` and hash written by `release_manifest` |
| News release-gate lineage | PASS | 51 targeted release/news gate tests; mismatched market snapshot fails closed |
| News Mini App browser rendering | NEEDS_REVERIFY | requires a real ready Pages release and browser evidence |
| Railway/Telegram production acceptance | BLOCKED | protected runtime configuration and controlled recipient evidence are external prerequisites |

`PASS` is not promoted to `LOCKED` for the two external rows because the
required objective evidence is not available in this checkout.

## Affected requirement traceability

| Requirement | Task | Implementation | Verification | Regression | Status |
|---|---|---|---|---|---|
| REQ-P0-04-DOD-NEWS-01 | Bind News to release | `src/release_manifest.py`, `schemas/release-manifest.schema.json` | manifest News artifact test | mixed-release fixture | PASS |
| REQ-P0-05-DOD-NEWS-02 | Verify before notify | `src/release_gate.py` | local release-gate suite | hash and snapshot mismatch | PASS |
| REQ-P0-14-DOD-NEWS-03 | Official source isolation | `src/news_feed_adapters.py`, `src/risk_news.py` | adapter parser/429 tests | one provider failure does not drop others | PASS |
| REQ-P0-20-DOD-NEWS-04 | Public UI evidence | `site/app.js` | browser/Pages smoke | release mismatch fallback | NEEDS_REVERIFY |

## Regression ledger

| Regression ID | Introduced by | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|---|
| REG-NEWS-001 | prior release path | News artifact could be hashed but not checked by delivery gate | gate loader enumerated only core/Creator artifacts | `7f1fd60`, 51 targeted tests | CLOSED |
| REG-NEWS-002 | environment | Windows shared temp contains inaccessible historical pytest directories | inherited workspace hygiene | CI and isolated basetemp pass; no product assertion changed | ACCEPTED ENVIRONMENT DEBT |

## Completion debt ledger

| Debt ID | Description | Resolution / owner | Status |
|---|---|---|---|
| DEBT-NEWS-001 | Live official feed and Pages publication evidence | run controlled release after PR #577 is merged | OPEN EXTERNAL |
| DEBT-NEWS-002 | Railway and Telegram delivery receipt evidence | protected runtime configuration; single-recipient dry-run | OPEN EXTERNAL |
| DEBT-NEWS-003 | Historical untracked test/temp artifacts | separate workspace hygiene task; do not stage during feature work | OPEN NON-PRODUCTION |

## Gate decision

The canonical News release-lineage task is complete on this branch.  Do not
merge solely from local evidence while PR checks are pending.  After remote
checks are green, the remaining work is the Pages browser and protected
Railway/Telegram acceptance gates; no production side effect is attempted by
this checkpoint.
