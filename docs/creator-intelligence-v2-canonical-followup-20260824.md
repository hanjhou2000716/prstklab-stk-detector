# Creator Intelligence V2 canonical follow-up — 2026-08-24

This follow-up preserves the existing release gate and adds only deterministic
contract hardening. It does not expose raw Gmail content, attachment bytes,
private paths, or recipient identifiers.

## Changes

- The canonical provider registry now distinguishes the two mandatory 10:30
  providers (`haojiao`, `jenny`) from optional daily providers (`gooaye`).
  Jenny's public display name is `財女珍妮`.
- Jenny parsing is versioned as `jenny-template-v2`. Explicitly labelled
  topics, markets, sectors, tickers, creator views and key numbers are kept as
  attributed evidence; arbitrary prose is never promoted to a ticker or signal.
- Validated private media can be deterministically bound to an observation and
  episode. Invalid or missing media degrades to `text_only`; it cannot produce
  a blank/black public card.
- FinancialJuice compound messages have a public-safe envelope. Items remain
  independent and unresolved boundaries are explicitly `compound_unresolved`.
- Mini App always exposes the 財經內容洞察 section. It distinguishes
  `尚未發布` from `來源待核對` and `資料可用`, rather than hiding missing data.

## Verification

```text
node --check site/app.js
python scripts/sync_railway_canonical_parser.py --check
python -m pytest -q tests/test_creator_provider_registry.py \
  tests/test_creator_source_adapters.py tests/test_creator_morning_batch.py \
  tests/test_creator_media_provenance.py tests/test_financialjuice_envelope.py \
  tests/test_mini_app_assets.py tests/test_mini_app_layout.py \
  tests/test_mini_app_browser_contract.py tests/test_news_intelligence.py \
  tests/test_news_feed_adapters.py
```

The targeted suite passed locally (91 tests). Live Railway/Gmail/Pages and
single-recipient Telegram evidence remains a separate production-acceptance
gate; local tests do not claim that external acceptance.

## Rollback

Revert this atomic change and restore the previous immutable data-release.
Do not mix creator, market and event artifacts from different releases.
