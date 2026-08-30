# PRStK Production Repair — Combined Final Batch

本批次以目前 `main` 為基準，將三個根因修復放在同一個可回溯變更中。

## Gate traceability

| Requirement | Implementation | Verification | State |
|---|---|---|---|
| TASK-01 Taiwan turnover denominator | `fetch_taiwan_official_share_records`, `run_value_quality_scan` | official TWSE/TPEx parser, cache-basis and missing-data tests; live endpoint audit 2026-08-30 | PASS (local/live adapter) |
| TASK-01 candidate/data-gap semantics | value scan summary fields and explicit share errors | value scan contract tests | PASS (local) |
| TASK-02 relevance-first US news | additive official + Anue + Yahoo Finance + Google pool; generic SEC exclusion | news intelligence/routing tests | PASS (local) |
| TASK-03 non-Creator delivery | `production_text_acceptance`, text-only legacy smoke, workflow without renderer/photo | workflow, smoke, contract tests | PASS (local) |
| TASK-03 canonical R-level | `short_event_message` and official event formatter | event output and Telegram contract tests | PASS (local) |

## Safety and preservation

- Taiwan Yahoo float/outstanding values are never used as an incompatible
  denominator; missing official shares remain a data gap.
- SEC generic filings remain diagnostic only and cannot fill public US top five.
- Creator attachment delivery remains the only production photo exception.
- Scheduled, emergency, FinancialJuice, smoke, and acceptance paths send text;
  release verification precedes delivery and receipts retain release/snapshot IDs.
- Existing renderer and photo client remain available for Creator/CI-only use.

## Open evidence

Live Pages, Railway/Worker callback, and a real Telegram recipient must be run
as a post-merge acceptance gate. No production broadcast is performed by this
change.
