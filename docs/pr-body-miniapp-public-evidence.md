## Summary

- record the publicly observable Mini App release and manifest lineage on 2026-08-21;
- document Creator/news, source-health, research-stale and briefing states observed on Pages;
- keep external Railway/Gmail/GDELT and single-recipient delivery gates explicitly NEEDS_REVERIFY.

## Dependency

- Based on the current `main` release (`bdf5df8`).
- No code, schema, data-release or secret changes.

## Verification

- `git diff --check`
- `uv run pytest -q tests/test_release_gate.py tests/test_release_manifest.py tests/test_mini_app_layout.py tests/test_mini_app_assets.py tests/test_news_intelligence.py --tb=short --basetemp=.pytest-miniapp` (109 passed)
- Read-only public Pages manifest and Mini App DOM verification; no browser console errors observed.

## Failure cases and remaining gates

- Invalid manifests remain blocked from public deployment.
- Research stale fallback remains visible and cannot trigger high-risk alerts.
- Railway Gmail OAuth/Pub/Sub, canonical secret migration, GDELT recovery and constrained Creator/FinancialJuice receipt still require external evidence.

## Rollback

Revert this documentation-only PR. Runtime behavior and release artifacts are unchanged.
