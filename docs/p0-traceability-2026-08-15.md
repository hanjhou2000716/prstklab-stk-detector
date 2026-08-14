# P0 requirement traceability (Gate-Driven v3)

This is the current reconciliation of the 29 mandatory P0 requirements from
the Creator Intelligence / FinancialJuice / News Intelligence brief.  It is
the evidence index for this migration; older gate notes remain historical
evidence and cannot upgrade a row by themselves.

Every row has three deterministic DoD IDs:

- `DOD-01`: implementation is present in the canonical production path;
- `DOD-02`: required verification and objective evidence exist;
- `DOD-03`: preservation/regression evidence exists and no open debt is hidden.

`PASS` is intentionally rare.  `NEEDS_REVERIFY` means code or historical
evidence exists, but the current main/release acceptance gate has not yet been
re-run after this migration.  No row below is allowed to imply that missing
evidence means the feature is safe or complete.

| Requirement | Task | Implementation | Verification / evidence | Regression / preservation | Status |
|---|---|---|---|---|---|
| P0-01 Canonical Creator Provider Registry | `REQ-P0-01-DOD-01..03` | `src/creator_provider_registry.py`, provider schema | Registry/parser/routing tests; historical PR #565 | Unknown provider remains fail-closed | `PASS / LOCKED` |
| P0-02 Jenny source adapter + parser | `REQ-P0-02-DOD-01..03` | `src/creator_source_adapters.py`, `src/external_source_parsers.py` | Parser fixtures and source-health tests | Malformed source cannot enter public output | `NEEDS_REVERIFY` |
| P0-03 Jenny attachment/media provenance | `REQ-P0-03-DOD-01..03` | `src/creator_media.py`, `src/creator_photo_delivery.py` | Media boundary and hash tests | Raw attachment remains private | `NEEDS_REVERIFY` |
| P0-04 10:30 morning creator batch | `REQ-P0-04-DOD-01..03` | `src/creator_refresh.py`, scheduled workflow | Batch/idempotency tests; production schedule not replayed | Duplicate batch must not redeliver | `NEEDS_REVERIFY` |
| P0-05 Creator Consensus V2 | `REQ-P0-05-DOD-01..03` | `src/creator_consensus.py` | Consensus fixtures and disagreement tests | Missing source lowers confidence, never invents agreement | `NEEDS_REVERIFY` |
| P0-06 Consensus × PRStK cross analysis | `REQ-P0-06-DOD-01..03` | `src/creator_correlation.py`, `src/creator_intelligence_pipeline.py` | Correlation and no-match tests | Creator opinion never becomes a standalone signal | `NEEDS_REVERIFY` |
| P0-07 Creator public artifact V2 | `REQ-P0-07-DOD-01..03` | `src/creator_artifact.py`, `src/creator_release.py` | Public artifact schema/hash tests | Raw email/media are excluded | `NEEDS_REVERIFY` |
| P0-08 Creator Mini App UX | `REQ-P0-08-DOD-01..03` | `site/app.js`, creator release loader | Browser contract and fallback tests | Release mismatch fails closed | `NEEDS_REVERIFY` |
| P0-09 FinancialJuice compound parser | `REQ-P0-09-DOD-01..03` | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | Compound fan-out fixtures and 19+ targeted tests | Unresolved items remain non-deliverable | `PASS / LOCKED` |
| P0-10 FinancialJuice priority policy | `REQ-P0-10-DOD-01..03` | `src/financialjuice_contract.py` | 8/10 eligible, 7/10 rejected, risk unchanged tests | Vendor priority cannot override PRStK risk | `PASS / LOCKED` |
| P0-11 cluster-aware deduplication | `REQ-P0-11-DOD-01..03` | `src/event_ledger.py`, `src/alert_budget.py` | Identity/cooldown/lifecycle tests | Polling cannot reset the event budget | `PASS / LOCKED` |
| P0-12 FinancialJuice production lane | `REQ-P0-12-DOD-01..03` | `src/scheduled_delivery.py`, Railway observation client | 17+ gateway/client and 27 pipeline tests; Railway acceptance pending | Missing URL/secret remains fail-closed | `NEEDS_REVERIFY` |
| P0-13 FinancialJuice risk card UI | `REQ-P0-13-DOD-01..03` | `src/briefing_cards.py`, `site/app.js` | Card fixtures exist; current public release not replayed | No evidence means no risk escalation | `NEEDS_REVERIFY` |
| P0-14 news provider registry | `REQ-P0-14-DOD-01..03` | `src/event_source_catalog.py`, news adapters | Catalog/source-health tests | Unregistered provider cannot publish | `NEEDS_REVERIFY` |
| P0-15 normalized NewsStory contract | `REQ-P0-15-DOD-01..03` | `src/intelligence_contract.py`, `src/external_event_pipeline.py` | Schema and normalization tests | Missing provenance is rejected | `NEEDS_REVERIFY` |
| P0-16 news interest graph | `REQ-P0-16-DOD-01..03` | `src/market_impact_graph.py` | Graph evidence tests | No market evidence remains conditional | `NEEDS_REVERIFY` |
| P0-17 news relevance ranking | `REQ-P0-17-DOD-01..03` | `src/event_classifier.py`, `src/intelligence_pipeline.py` | Classification/ranking fixtures | Low-confidence stories stay observation-only | `NEEDS_REVERIFY` |
| P0-18 news deduplication | `REQ-P0-18-DOD-01..03` | `src/event_ledger.py`, `src/material_change.py` | Repeated poll and material-change tests | Only lifecycle/material changes can notify | `NEEDS_REVERIFY` |
| P0-19 frontend URL security | `REQ-P0-19-DOD-01..03` | `site/app.js`, `src/deep_link_router.py` | Deep-link and URL allowlist tests | Cross-release mismatch cannot route | `NEEDS_REVERIFY` |
| P0-20 market-news Mini App UX | `REQ-P0-20-DOD-01..03` | `site/app.js`, news routing contract | Browser/news routing tests | Empty result is distinct from provider failure | `NEEDS_REVERIFY` |
| P0-21 Creator Telegram rendering | `REQ-P0-21-DOD-01..03` | `src/creator_photo_delivery.py`, `src/alert_card_renderer.py` | Photo contract and renderer tests | Renderer failure is fail-closed | `NEEDS_REVERIFY` |
| P0-22 late Creator delivery | `REQ-P0-22-DOD-01..03` | `src/creator_dispatch.py`, `src/creator_delivery_store.py` | Idempotency/late-delivery tests | Delivery receipt is release-bound | `NEEDS_REVERIFY` |
| P0-23 Gooaye daily behavior | `REQ-P0-23-DOD-01..03` | creator provider registry and policy adapters | Provider behavior fixtures | Unknown/unsupported provider is observe-only | `NEEDS_REVERIFY` |
| P0-24 observability | `REQ-P0-24-DOD-01..03` | `src/health_observability.py`, `railway-monitor/app.py` | Health and delivery receipt tests | Secrets and recipient IDs stay out of logs | `NEEDS_REVERIFY` |
| P0-25 failure semantics | `REQ-P0-25-DOD-01..03` | `src/research_scan_state.py`, release gate | Failure-ledger and fail-closed tests | No event is distinct from scan failure | `NEEDS_REVERIFY` |
| P0-26 Railway architecture cleanup | `REQ-P0-26-DOD-01..03` | `railway-monitor/*`, `src/railway_observation_client.py` | Auth/schema/client tests; deploy acceptance pending | Railway outage cannot invent data | `NEEDS_REVERIFY` |
| P0-27 release contract | `REQ-P0-27-DOD-01..03` | `src/release_manifest.py`, `src/release_gate.py` | Manifest/hash/propagation tests | Telegram follows a validated immutable release | `NEEDS_REVERIFY` |
| P0-28 security / privacy | `REQ-P0-28-DOD-01..03` | privacy allowlists, workflow permissions, security workflow | CodeQL/dependency/SBOM CI evidence | No raw email, secret or private portfolio in public artifacts | `NEEDS_REVERIFY` |
| P0-29 tests | `REQ-P0-29-DOD-01..03` | `tests/`, quality/security workflows | Targeted suites and PR #618 CI; full main regression pending | Open regression/debt prevents final PASS | `NEEDS_REVERIFY` |

## Current gate summary

- P0 rows: 29 total; 4 currently locked from objective evidence, 25 require
  current-main re-verification.
- The migration implementation in PR #618 is limited to the sanitized
  Railway observation path and this evidence index.  It does not silently
  promote the rest of the product to `PASS`.
- Railway deployment, Pages release verification and the single-recipient
  production acceptance test remain external gates and are not performed by
  this documentation PR.

## Recovery and rollback

This document is additive and contains no runtime behavior.  Reverting its
commit removes the index without changing release, notification or privacy
gates.  The authoritative code checkpoint remains the branch and commit listed
in `docs/gate-driven-migration-2026-08-15.md`.
