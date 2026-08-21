# News Interest Graph release binding

The market-news producer now binds every release-bound `news.intelligence`
view to the public context available at scan time:

- tracked watchlist tickers;
- research candidate tickers and sectors;
- active/recent event topic terms from the local event ledger;
- optional Creator-mentioned terms when a sanitized Creator artifact supplies
  them.

The context is written into `interest_graph.context`. Each ranked story keeps
its existing normalized `relevance_reasons` and adds source-specific reasons
such as `research_candidate:NVDA`, `tracked_ticker:NVDA`,
`active_event:iran`, or `creator_mentioned:nvidia`. Aggregate counts are
available under `interest_graph.source_interest`.

This is an explainability and ranking input only. It does not alter market
routing, event severity, release gates, or Telegram eligibility. Missing
context is represented by an empty list; it is never replaced with invented
entities. Alias matching is bounded to the tracked public instruments and
scans title/summary text for providers that omit structured ticker fields.

## Verification

- News intelligence and risk-news targeted tests cover title-only ticker
  matching, research-candidate reasons, event and Creator context, and the
  release snapshot binding.
- Full regression on this branch: `1310 passed, 1 skipped`.
- `uv run --locked ruff check` and `uv run --locked mypy src` pass.

## Rollback

Revert this PR. Existing `stories`, provider health, market routing and
release-gate behavior remain compatible because the new graph fields are
additive.
