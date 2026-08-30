# G4–G12 production repair traceability

This checkpoint records the migration audit for the G4–G12 requirements. A
module is `production` only when its producer, release JSON, public Mini App,
delivery path, and regression evidence all agree. File existence alone is not
evidence of production use.

| Module | File exists | Tests | Production pipeline | JSON | Mini App | Telegram | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Source Adapter | yes | yes | yes | yes | yes | no | production |
| Raw Observation Store | yes | yes | yes | yes | yes | no | production |
| Instrument Master | yes | yes | yes | yes | yes | no | production |
| Data Quality / Crosscheck | yes | yes | yes | yes | yes | yes | production |
| Event Source Catalog / Cluster | yes | yes | yes | yes | yes | yes | production |
| Macro Surprise | yes | yes | yes | yes | yes | yes | production |
| Corporate Event | yes | yes | yes | yes | yes | yes | production |
| Market Impact Graph | yes | yes | yes | yes | yes | yes | partially_integrated |
| Event Feedback / Timeline | yes | yes | yes | yes | yes | yes | production |
| Market Regime / Contagion | yes | yes | yes | yes | yes | yes | partially_integrated |
| Stress Scenario | yes | yes | yes | yes | yes | no | partially_integrated |
| Alert Lifecycle / Material Change | yes | yes | yes | yes | yes | yes | production |
| Alert Budget | yes | yes | yes | yes | no | yes | production |
| Portfolio Risk | yes | yes | isolated | no | private | no | production |
| Cost Model / Strategy Registry | yes | yes | yes | yes | yes | no | partially_integrated |
| Explainability / Advice Gate | yes | yes | yes | yes | backend | no | production |
| Paper Portfolio | yes | yes | yes | yes | yes | no | partially_integrated |
| Source Health | yes | yes | yes | yes | yes | yes | production |
| Release Gate / data-release | yes | yes | yes | yes | yes | yes | production |
| Telegram Delivery | yes | yes | yes | receipt | no | yes | production |

## Migration evidence

- Baseline was taken from `origin/main` at the merge of PR #829 and the latest
  `origin/data-release`; no pre-existing working-tree artifacts were removed.
- Targeted baseline tests: 110 passed. The changed-surface regression suite is
  recorded by the CI run and must pass before this branch is considered ready.
- Taiwan Macro FGI retains the fixed five-factor formula and now reports
  per-component health, original observation date, and an explicitly labelled
  bounded last-good fallback. It never turns a missing component into a fresh
  score.
- Public research cards no longer render the long “條件與風險說明” drawer;
  Creator/backend explainability remains available for audited reports.
- Public news cards translate internal relevance codes to human labels. Raw
  routing tokens are not rendered.

## Gate state

The implementation branch is not a release and must not replace the public
last-good release until targeted tests, full regression, schema/release audits,
and the production acceptance checks have passed. A failed release gate keeps
the previous public release active.

## Runtime configuration

- `TAIWAN_FGI_CACHE_PATH` (optional): writable path for the last successful
  five-factor FGI result. The cached date is retained and shown as stale when a
  component fails; it is never treated as a fresh observation.
- `PUBLIC_SHARE_CACHE_PATH` (optional): bounded public share-count cache for
  turnover-rate provenance. Missing shares remain incomplete and cannot pass a
  Pristine condition.
