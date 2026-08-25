# Evidence — news source diversity (2026-08-25)

## Scope

This change makes source breadth explicit in the canonical news artifact and
Mini App.  It does not change alert thresholds or treat a media aggregator as
an official confirmation.

## Local evidence

- `tests/test_news_intelligence.py`: independent domain counting and
  single-source pending state.
- `src/artifact_contract.py`: cross-field consistency checks for status,
  count, and `cross_checked`.
- `site/app.js`/`site/index.html`: Taiwan and US source status are rendered
  independently.

## Acceptance notes

The source-diversity field is additive for historical releases.  New artifacts
always include it; older artifacts continue to load, while any present but
contradictory summary is rejected before publication.
