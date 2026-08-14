# REQ-ADD-027 Creator evidence alignment

## Scope

Creator Intelligence now uses the existing PRStK market, research and event
snapshots as one evidence boundary. This is an extension of the canonical
pipeline, not a second classifier or delivery path.

## Contract

- Correlation records retain market, research and event snapshot IDs.
- Explicit tickers, sectors, candidates and affected instruments are matched;
  prose alone never establishes alignment.
- `evidence_alignment` is `aligned`, `partially_aligned`,
  `insufficient_evidence`, or `stale`.
- A stale snapshot is visible as stale evidence and cannot become a current
  investment signal.
- Creator output remains public-safe and `is_investment_signal=false`.
- Research lineage is optional for legacy releases, but is enforced whenever
  the parent release declares `research_snapshot_id`.

## Verification

- Creator correlation/release/manifest/briefing regression: 25 passed.
- Python compilation: passed.
- Ruff targeted check: passed via `uv run ruff check`.

## Rollback

Revert this atomic change. Existing Creator artifacts remain compatible because
research lineage is optional for legacy parent manifests.
