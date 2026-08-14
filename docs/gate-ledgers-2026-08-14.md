# Gate-Driven v3 ledgers

This ledger is evidence-driven: implementation, local verification, remote CI,
and external production acceptance are recorded separately. `PASS` below means
the repository evidence is complete for the listed boundary; production gates
remain `NEEDS_REVERIFY` until the controlled post-merge run is captured.

## Requirement traceability

| Requirement | Task | Implementation | Verification / evidence | Regression | Status |
|---|---|---|---|---|---|
| REQ-ADD-013 | source cache boundary | `railway-monitor/cache_store.py` | targeted 97; PR #590 CI green | GDELT stale-cache fail-closed tests | PASS / LOCKED |
| REQ-ADD-014 | health dispatch boundary | `railway-monitor/health_dispatch.py` | targeted 86; PR #591 CI green | 401/403/429/5xx callback tests | PASS / LOCKED |
| REQ-ADD-015 | dispatch payload boundary | `railway-monitor/dispatch_payload.py` | targeted 101; PR #592 CI green | HMAC and canonical-key tests | PASS / LOCKED |
| REQ-ADD-016 | Jin10 source adapter | `railway-monitor/jin10_source.py` | targeted 102; PR #593 CI green | schema negotiation and source-failure tests | PASS / LOCKED |
| REQ-ADD-017 | creator receipt projection | `railway-monitor/creator_delivery.py` | targeted 104; PR #594 CI green | private receipt projection tests | PASS / LOCKED |
| REQ-ADD-018 | delivery retry orchestration | `railway-monitor/delivery_retry.py` | targeted 106; PR #595 CI green | payload reuse and failure continuation | PASS / LOCKED |
| REQ-ADD-019 | alert dispatch orchestration | `railway-monitor/alert_dispatch.py` | targeted 107; PR #596 CI green | exact-once build/sign/send order | PASS / LOCKED |
| REQ-ADD-020 | market-sync reader | `railway-monitor/market_sync.py` | targeted 110; PR #597 CI green | missing/invalid snapshot fail-closed | PASS / LOCKED |
| REQ-ADD-022 | market-sync health envelope | `railway-monitor/market_sync.py`, `railway-monitor/app.py` | targeted 113; PR #599 CI green | valid-empty vs configuration/http/parser failure states | PASS / LOCKED |
| REQ-ADD-023 | GDELT source-health projection | `railway-monitor/gdelt_health.py`, `railway-monitor/app.py` | targeted 116; PR #600 CI green | no-event vs scan-failed vs stale-cache | PASS / LOCKED |
| REQ-ADD-024 | health baseline state | `railway-monitor/app.py` | targeted 117; PR #601 CI green | first-cycle values remain not_checked | PASS / LOCKED |
| REQ-ADD-025 | Mini App health baseline labels | `site/app.js`, `tests/test_mini_app_layout.py` | targeted 27; node syntax check; PR #603 CI green (run `31804138036` / `31804138042`) | not_checked is not rendered as a data gap | PASS / LOCKED |
| MIGRATION-001 | Gate-Driven recovery snapshot | `docs/gate-migration-snapshot-2026-08-14.md` | repository state, offline runtime audit, production E2E, PR #602 CI green | snapshot is documentation-only and preserves external debt | PASS / LOCKED |
| REQ-ADD-026 | Creator 10:30 morning batch contract and fan-out | `src/creator_morning_batch.py`, `src/creator_intelligence_pipeline.py`, `src/briefing_cards.py`, `src/creator_dispatch.py`, `src/creator_notification.py`, `src/creator_photo_delivery.py` | targeted batch/dispatch suite 20 passed; full isolated regression 1213 passed/1 skipped; Ruff/Mypy/compileall pass; PR #604 latest quality run `31811684845` and security run `31811684878` green | latest-per-creator, 2/2 episode+digest, partial/no-content separation, late-delta, restart idempotency | PASS / LOCKED (branch evidence) |
| REQ-ADD-027 | Creator evidence alignment across market/research/event snapshots | `src/creator_correlation.py`, `src/creator_intelligence_pipeline.py`, `src/creator_release.py`, `src/briefing_cards.py`, `src/release_manifest.py`, `src/release_gate.py`, `schemas/creator-release.schema.json` | targeted Creator lineage/correlation/manifest suite 25 passed; full regression 1216 passed/1 skipped; compileall, targeted Ruff and Mypy pass | explicit entity matching, stale evidence state, research lineage compatibility, no investment signal | PASS / LOCKED (branch evidence; production acceptance remains external) |
| REQ-ADD-028 | FinancialJuice sanitized compound envelope runtime ingress | `src/external_observation_input.py`, `tests/test_external_observation_input.py`, `docs/req-add-028-financialjuice-runtime-envelope.md` | targeted compound ingress/event suite 19 passed; full regression 1221 passed; Ruff/Mypy/compileall/runtime audit pass | private transport ID never propagates; unresolved/count-mismatch/raw-field inputs fail closed; flat input preserved | PASS / LOCKED (branch evidence; production acceptance remains external) |
| REQ-ADD-029 | Intelligence direct-input privacy boundary | `src/intelligence_pipeline.py`, `tests/test_intelligence_pipeline_external_risk.py`, `docs/req-add-029-intelligence-privacy-boundary.md` | targeted intelligence/contract suite 11 passed; full regression 1222 passed; Ruff/Mypy/compileall pass | direct compound input strips transport/raw fields; unresolved envelopes do not become events | PASS / LOCKED (branch evidence; production acceptance remains external) |
| REQ-ADD-030 | External event pipeline privacy boundary | `src/external_event_pipeline.py`, `tests/test_external_event_pipeline.py`, `docs/req-add-030-external-event-privacy-boundary.md` | targeted external/privacy suite 21 passed; full isolated regression 1223 passed; Ruff/Mypy/compileall pass | unresolved compound IDs and generic Gmail transport IDs never enter output or evidence | PASS / LOCKED (branch evidence; production acceptance remains external) |
| REQ-ADD-031 | Gate-Driven P0 requirement traceability matrix | `docs/p0-requirement-traceability-2026-08-15.md` | `git diff --check`; PR #609 quality/security CI green | documentation-only; no runtime or release artifact change | PASS / LOCKED (documentation evidence; production debt remains external) |
| REQ-ADD-032 | raw observation persistence retries for transient Windows/SQLite locks | `src/raw_observation_store.py` | targeted 17 passed; Ruff/Mypy/compileall pass; full regression 1224 passed | no schema or release artifact change; non-retryable errors remain fail-closed | PASS / LOCKED (local evidence; production acceptance remains external) |
| REQ-ADD-033 | Railway Gmail registry bundle and shared publish-lock retry boundary | `railway-monitor/email_router.py`, `railway-monitor/creator_providers.json`, `src/atomic_file.py`, `src/build_assets.py`, `src/refresh_market_data.py`, `src/release_manifest.py` | standalone Railway import and atomic publish suites 54 passed; targeted Ruff/compileall pass; full regression 1226 passed | Railway health must confirm Gmail no longer reports `ModuleNotFoundError`; OAuth/PubSub and callback permissions remain external | canonical parser/delivery path preserved; non-retryable publish errors remain fail-closed | PASS / LOCKED (local evidence; production acceptance remains external) |

## Regression ledger

| Regression ID | Introduced by | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|---|
| REG-001 | REQ-ADD-013..020 | none observed in targeted suite | n/a | 110-test stacked Railway suite plus CI | CLOSED |
| REG-002 | legacy runtime | live Railway restart/cache continuity not proven in local CI | external volume/runtime | controlled Railway acceptance required | OPEN / EXTERNAL |
| REG-003 | legacy delivery | signed callback and Telegram receipt not proven in local CI | external credentials/recipient | single-recipient controlled E2E required | OPEN / EXTERNAL |
| REG-004 | REQ-ADD-028 | compound FinancialJuice envelope was rejected by the scheduled observation loader | loader accepted only flat `observations` arrays | envelope flattening plus fail-closed item contract; 19 targeted and 1221 full tests | CLOSED |
| REG-005 | REQ-ADD-029 | direct intelligence callers could retain envelope transport IDs | compound flattening copied `message_id` into event observations | shared defensive sanitizer; 11 targeted tests | CLOSED |
| REG-006 | REQ-ADD-030 | direct external-event callers could expose transport IDs in observation/evidence output | pipeline accepted raw records and used `gmail_message_id` as an observation fallback | recursive public-field sanitizer plus unresolved-ID suppression; 21 targeted and 1223 full tests | CLOSED |
| REG-007 | REQ-ADD-032 | transient Windows/OneDrive file locks could turn raw observation writes into `unavailable` | atomic replace had no bounded retry; concurrent SQLite writers had no busy backoff | bounded file-lock retry, SQLite busy timeout/backoff; 17 targeted and 1224 full tests | CLOSED |
| REG-008 | REQ-ADD-033 | `build_assets` could fail the Pages publish job on a transient OneDrive/Windows `PermissionError` during atomic replace | the publish helper had no bounded retry | shared `src.atomic_file.replace_with_retry` used by raw observation, asset, market snapshot and release manifest writes; transient-lock fixture added; 1226 full tests | CLOSED |

## Completion debt ledger

| Debt ID | Description | Source | Resolution | Status |
|---|---|---|---|---|
| DEBT-001 | Run post-merge Railway restart/cache continuity check | production gate | execute against the merged main release | OPEN / EXTERNAL |
| DEBT-002 | Capture signed callback and Telegram delivery receipt | production gate | use one approved test recipient only | OPEN / EXTERNAL |
| DEBT-003 | Verify Pages release propagation and public market snapshot freshness | production gate | public manifest/hash/snapshot IDs verified 2026-08-15; release age remains explicit | CLOSED (lineage); freshness observation remains external |
| DEBT-FJ-002 | FinancialJuice runtime bundle is not yet observed in Railway | production gate | configure reviewed sanitized bundle path and capture source-health/release evidence | OPEN / EXTERNAL |

No implementation task in REQ-ADD-013..020 is marked PASS solely because a PR
exists; each has local and remote evidence above. External debt must be closed
before the final production acceptance gate.

Latest migration-head regression: `1207 passed` in `77.01s` at
`76241c7872369be0ebfd0cb6f1adfadbb9e00b5e` using an isolated Windows temp
directory. This evidence does not imply live Railway/Pages/Telegram acceptance.

## Migration verification snapshot (2026-08-14)

The post-PR-604 local gate was rerun against the stacked branch:

- `python -m src.runtime_audit`: **PASS** (`ok=true`, no invariant issues).
- `python -m compileall -q src`: **PASS**.
- `node --check site/app.js`: **PASS**.
- `python -m src.delivery_smoke_test`: **BLOCKED / EXTERNAL** because the
  isolated local environment intentionally has no `TELEGRAM_CHAT_IDS`.

The delivery smoke failure is not a code failure and must not be hidden by a
test bypass. It remains covered by the controlled single-recipient production
gate (DEBT-002), which requires the configured test recipient and a signed
Railway receipt. No production notification was sent during this local check.
