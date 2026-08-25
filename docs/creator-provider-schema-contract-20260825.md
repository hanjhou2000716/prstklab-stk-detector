# Creator provider schema contract (2026-08-25)

The canonical Creator registry is `config/creator_providers.json`. Its
machine-readable contract is `schemas/creator-providers.schema.json` and is
validated before semantic normalization. This makes unsupported fields,
unknown source types, missing identity markers, and notification-policy drift
fail closed instead of being silently accepted by one consumer.

The Railway parser image receives the same schema under
`railway-monitor/schemas/creator-providers.schema.json`. The bundle generator
and canonical-overlap audit compare the runtime copy with the repository
source, so the parser cannot silently use a different provider definition.

## Verification evidence

- Creator registry, bundle parity, and schema tests: 13 passed.
- Full repository regression after this change: 1451 passed.
- Ruff, `compileall`, `verify_canonical_overlap.py`, and
  `verify_intelligence_contracts.py`: passed.
- PR #779 required Actions: test-and-dry-run, CodeQL, dependency review and
  SBOM: passed.

This is a local/CI contract result. It does not claim that Railway has already
deployed the new bundle or that Gmail/Creator observations have arrived.
Those remain external acceptance gates and must be reverified after the
stacked PRs are merged.

## Rollback

Revert PR #779. The prior semantic checks remain available, while the formal
schema gate and bundled schema are removed. Do not mix a previous provider
registry with a newer Creator release artifact.
