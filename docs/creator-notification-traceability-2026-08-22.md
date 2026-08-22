# Creator／FinancialJuice／News Gate Traceability

This is the migration checkpoint for the canonical Creator Intelligence V2
path. A `PASS` below means there is local implementation plus reproducible
verification evidence; it does not claim that an external provider is
configured or that a production recipient received a message.

| Requirement | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|
| Creator identity and public-safe sanitization | `src/creator_provider_registry.py`, `src/creator_source_adapters.py`, `src/creator_intelligence_pipeline.py` | parser, registry and release tests | `uv run pytest` targeted suite | private fields remain rejected | PASS |
| Creator editorial content remains attributed, not a market signal | `src/creator_artifact.py`, `src/creator_intelligence_pipeline.py` | release contract tests | `tests/test_creator_*` | no directional risk field | PASS |
| 10:30 batch, partial state and late arrivals | `src/creator_morning_batch.py` | cutoff and late-arrival tests | `creator_morning_batch_lane` | future rows rejected | PASS |
| Creator photo/text notification contract | `src/creator_notification.py`, `src/creator_photo_delivery.py` | photo, fallback and idempotency tests | `creator-notification-offline-e2e-2026-08-22.json` | no black/empty fallback | PASS |
| Per-recipient isolation and privacy-safe receipt | `src/creator_notification.py`, `src/creator_photo_delivery.py` | two-recipient injected sender | offline E2E receipt statuses | raw chat IDs excluded | PASS |
| Morning digest and late-delta deduplication | `src/creator_notification.py` | digest/replay/late-delta lane | offline E2E | repeated key suppressed | PASS |
| Creator Consensus V2 and Creator×PRStK evidence correlation | `src/creator_consensus.py`, `src/creator_correlation.py`, `src/creator_intelligence_e2e.py` | latest-per-creator, aligned, divergent and correlation fixtures | `creator-intelligence-offline-e2e-2026-08-22.json` | consensus never becomes an investment signal; divergence remains visible | PASS |
| FinancialJuice compound parsing and priority | `src/external_source_parsers.py`, `src/financialjuice_priority.py` | compound fixture | `financialjuice_compound_lane` | vendor importance cannot change PRStK risk | PASS |
| FinancialJuice release-gated Telegram delivery | `src/financialjuice_notification.py`, `src/financialjuice_notification_e2e.py`, `src/scheduled_delivery.py` | injected sendPhoto lane, partial recipient retry and replay | `financialjuice-notification-offline-e2e-2026-08-22.json` | no send before release gate; recipient IDs remain hashed | PASS |
| FinancialJuice Mini App evidence card | `site/app.js`, `site/styles.css`, `tests/test_mini_app_browser_contract.py` | static UI contract, hash-bound browser fixture, JavaScript syntax check | `financialjuice-miniapp-ui-2026-08-22.json`, `financialjuice-miniapp-browser-e2e-2026-08-22.json` (quality run 32548163338; security run 32548163385) | vendor priority remains separate from PRStK risk; release/snapshot/observation lineage and waiting state remain visible in the real DOM | PASS |
| Release-gated single-recipient photo acceptance | `src/production_photo_smoke_test.py`, `.github/workflows/production-acceptance-photo.yml` | release-gate, renderer-dimension and one-recipient unit tests | `tests/test_production_photo_smoke_test.py` (offline only) | blocked releases never call Telegram; external delivery remains manual and scoped to one recipient | PASS (offline) / NEEDS_REVERIFY (external) |
| FinancialJuice live Gmail ingress | Railway Gmail watch/PubSub configuration | read-only Railway health snapshot; controlled receipt still pending | `external-acceptance-2026-08-22T1115.json` (configuration-missing) | no fabricated event | NEEDS_REVERIFY |
| Official-first news registry, routing, ranking and dedupe | `src/news_intelligence.py`, `src/news_feed_adapters.py`, `src/risk_news.py`, `src/creator_intelligence_e2e.py` | provider/domain/dedupe tests plus Taiwan/US scoped offline lane | `creator-intelligence-offline-e2e-2026-08-22.json` | Taiwan and US feeds exclude incompatible official sources; source failure remains visible | PASS |
| Publish-before-notify and release binding | `src/release_gate.py`, `src/creator_dispatch.py`, `src/production_e2e.py` | release and offline E2E | production E2E report | invalid release blocks delivery | PASS |
| Railway/GDELT external acceptance | `railway-monitor/`, `src/gdelt_client.py` | health endpoint and callback | `external-acceptance-2026-08-22T1115.json` | bounded 429/403 handling | NEEDS_REVERIFY |

## Verification commands

```text
uv run pytest -q --basetemp .pytest-creator-e2e-20260822 \
  tests/test_creator_notification_e2e.py tests/test_production_e2e.py \
  tests/test_financialjuice_notification_e2e.py \
  tests/test_creator_notification.py tests/test_creator_morning_batch.py \
  tests/test_financialjuice_priority.py tests/test_creator_intelligence_e2e.py \
  tests/test_creator_consensus.py tests/test_creator_correlation.py \
  tests/test_news_intelligence.py
uv run python -m src.production_e2e
uv run python scripts/verify_canonical_overlap.py
python -m compileall -q src railway-monitor
node --check site/app.js
```

The offline lane uses injected senders and synthetic recipient labels only. It
does not contact Telegram, Gmail, Railway or market providers. Production
acceptance remains a separate gate and must not be promoted from this local
evidence.
