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

Latest migration-head regression: `1207 passed` in `121.49s` at
`1415f900a55dd39be0afe1fca985d9c087eebbea` using an isolated Windows temp
directory. This evidence does not imply live Railway/Pages/Telegram acceptance.
