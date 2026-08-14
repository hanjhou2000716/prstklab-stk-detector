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
| REQ-ADD-026 | Creator 10:30 morning batch contract and fan-out | `src/creator_morning_batch.py`, `src/creator_intelligence_pipeline.py`, `src/briefing_cards.py`, `src/creator_dispatch.py`, `src/creator_notification.py`, `src/creator_photo_delivery.py` | targeted batch/dispatch suite 20 passed; full isolated regression 1213 passed/1 skipped; Ruff/Mypy/compileall pass; PR #604 quality run `31810755218` and security run `31810755278` green | latest-per-creator, 2/2 episode+digest, partial/no-content separation, late-delta, restart idempotency | PASS / LOCKED (branch evidence) |

## Regression ledger

| Regression ID | Introduced by | Symptom | Root cause | Fix / evidence | Status |
|---|---|---|---|---|---|
| REG-001 | REQ-ADD-013..020 | none observed in targeted suite | n/a | 110-test stacked Railway suite plus CI | CLOSED |
| REG-002 | legacy runtime | live Railway restart/cache continuity not proven in local CI | external volume/runtime | controlled Railway acceptance required | OPEN / EXTERNAL |
| REG-003 | legacy delivery | signed callback and Telegram receipt not proven in local CI | external credentials/recipient | single-recipient controlled E2E required | OPEN / EXTERNAL |

## Completion debt ledger

| Debt ID | Description | Source | Resolution | Status |
|---|---|---|---|---|
| DEBT-001 | Run post-merge Railway restart/cache continuity check | production gate | execute against the merged main release | OPEN / EXTERNAL |
| DEBT-002 | Capture signed callback and Telegram delivery receipt | production gate | use one approved test recipient only | OPEN / EXTERNAL |
| DEBT-003 | Verify Pages release propagation and public market snapshot freshness | production gate | compare manifest/hash/snapshot IDs after deploy | OPEN / EXTERNAL |

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
