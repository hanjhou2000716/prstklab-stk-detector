# Creator／FinancialJuice Continuation Gate Audit（2026-08-20）

這份紀錄是目前主線的 overlap／evidence reconciliation checkpoint。它不新增
第二套 Creator、FinancialJuice、新聞、Release Gate 或 Telegram pipeline；
canonical ownership 仍以 `config/creator_providers.json`、
`src/financialjuice_contract.py`、`src/news_intelligence.py`、
`src/release_gate.py` 與既有 `src/scheduled_delivery.py` 為準。

## Current main and public release

| Item | Evidence |
|---|---|
| Main HEAD | `48a80afbae8808e196be901b3f36372e18f62ea8` |
| Latest merged evidence PR | [#644](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/644) |
| Refresh workflow | [32367236489](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32367236489) — success |
| Public manifest | `status=ready`, HTTP 200 |
| Release | `release-405b5923867d9d8b` |
| Market snapshot | `198c76b59a16a616` |
| Research snapshot | `research-8b8ec8f6e5ee51aa` |
| Event snapshot | `event-ed531dee05c7de49` |
| Creator / news state | `ready` / `ready` |

The refreshed manifest contains no validation errors. Market, research, event,
source-health, news, creator-release and creator-insights artifacts are loaded
through the same release boundary; no artifact is mixed across releases.

## Canonical overlap decisions

| Domain | Canonical owner | Compatibility boundary | Status |
|---|---|---|---|
| Creator provider identity and routing | `src/creator_provider_registry.py`, `config/creator_providers.json` | Generated `railway-monitor/creator_providers.json` | PASS / LOCKED (local) |
| Creator parser and public artifact | `src/creator_source_adapters.py`, `src/creator_artifact.py`, `src/creator_intelligence_pipeline.py` | Sanitized Railway bundle; no raw mail in `site/` | PASS / LOCKED (local) |
| Creator consensus and PRStK correlation | `src/creator_consensus.py`, `src/creator_correlation.py` | Briefing/release producer | PASS / LOCKED (local) |
| FinancialJuice compound parsing and priority policy | `src/external_source_parsers.py`, `src/financialjuice_contract.py` | `railway-monitor/email_router.py` only routes transport | PASS / LOCKED (local) |
| Official/news registry, relevance and dedup | `src/news_intelligence.py`, `src/news_feed_adapters.py`, `src/risk_news.py` | `site/app.js` consumes release-bound stories only | PASS / LOCKED (local) |
| Release and notification gate | `src/release_gate.py`, `src/release_manifest.py`, `src/scheduled_delivery.py` | Pages propagation and Telegram receipt callbacks | PASS / LOCKED (local + public release) |
| Railway runtime bundle | `railway-monitor/shared_event_classifier.py`, `railway-monitor/creator_providers.json` | Generated from repository canonical sources | PASS / LOCKED (deployed health) |

No additional parser, classifier, provider registry or notification policy was
created during this continuation. This prevents the Creator／FinancialJuice
overlap from reintroducing parallel logic.

## Verification evidence

| Gate | Result | Evidence |
|---|---|---|
| Full repository regression | PASS | 1261 tests passed; coverage 81.06% |
| Ruff / Mypy | PASS | `ruff check src tests`; `mypy src` |
| Compile / JS syntax | PASS | Python `compileall`; `node --check site/app.js` |
| Offline production E2E | PASS | fixed 1080×1350 renderer, mock Telegram, release/deep-link contracts |
| External intelligence fixture | PASS | sanitized FinancialJuice compound fixture; no credential/network use |
| Public release smoke | PASS | release manifest and declared artifact hashes verified |
| Telegram photo smoke | PASS | [Actions #32366252888](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32366252888): delivered 1, failed 0, one controlled recipient |
| Railway delivery receipt | PASS | callback accepted; receipt trace matched the smoke outbox trace |
| Railway health | PASS | HTTP 200, runtime healthy, classifier mode repository-shared |

The Telegram test is explicitly a single-recipient controlled smoke. It does
not prove that every future recipient has started the Bot, and it is not a
broadcast acceptance test.

## Remaining external gates

These are real external configuration／provider limitations, not hidden as
success and not used to create high-risk alerts:

1. Gmail ingress is `configuration_missing`; OAuth／PubSub credentials must be
   configured before live Creator／FinancialJuice mail can be accepted.
2. GDELT is currently `HTTP_429`; bounded backoff and stale-cache rules remain
   active, and no stale result is promoted to live evidence.
3. The GDELT health callback is `HTTP_403`; Railway local health remains the
   authoritative status and callback failures are non-fatal.

Until these external gates are configured or recovered, the system remains
fail-closed for those providers. Core market releases and valid public Pages
releases remain publishable; optional Creator／FinancialJuice input cannot
replace official or market evidence.

## Rollback

This is documentation only. Revert this commit to remove the audit record; it
does not alter market artifacts, Railway state, secrets or Telegram delivery.
