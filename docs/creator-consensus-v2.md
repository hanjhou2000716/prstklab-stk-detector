# Creator Consensus V2

Creator Intelligence is a public-content observation lane, not an event
source and not an investment signal.  The pipeline now selects the latest
valid episode for each creator, normalizes deterministic topic aliases, and
keeps aligned and divergent views visible in both `creator-release.json` and
`creator-insights.json`.

## Contract

- `coverage` reports unique latest creators (`2/2` means two current sources).
- `topic_consensus` is comparable only when at least two creators cover the
  canonical topic and provide an explicit `consensus_stance`.
- `mixed` is preserved; it is never flattened into a neutral or directional
  market conclusion.
- `evidence_alignment` comes only from the existing market/research/event
  correlation contract.  Stale or missing evidence remains visible.
- `is_investment_signal` is always `false`; no Creator content can trigger a
  buy/sell or high-risk event alert.
- The Mini App displays status, coverage, topic agreement/divergence, common
  risk tags, evidence alignment and timestamp without displaying an
  uncalibrated confidence number.

## Rollback

Revert this PR to remove the V2 projection.  The parent market release remains
valid because Creator Intelligence is an additive, independently fail-closed
artifact.  Existing 1.0 artifacts remain readable; new artifacts include the
optional `creator_consensus` object under the backward-compatible schema.
