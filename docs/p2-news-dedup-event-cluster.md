# P2-18 News event clustering

The public news contract now keeps two identities:

- `dedupe_key`: normalized headline identity for exact or near-identical
  headlines.
- `event_cluster_key`: deterministic identity built from bounded canonical
  entities, event topics, and a two-hour UTC publication bucket.

The cluster key is used only to merge supporting reports from different
providers. It never changes market scope, risk severity, or Telegram
eligibility. The highest-authority story remains the primary row and the
other URLs are retained in `supporting_sources`.

Safety rules:

- A lone generic ticker without a topic does not create a cluster key.
- Unknown or non-HTTPS URLs remain excluded from public ranking.
- Missing publication time uses an explicit `unknown` bucket and never claims
  recency.
- Different topics in the same time window remain separate events.

Rollback: revert this producer and schema change; the legacy headline
`dedupe_key` remains compatible with older release readers.
