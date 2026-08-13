# Creator source health runtime

Creator feeds are optional enrichment providers and now appear in the same
published `source_health` contract as the market sources when the scheduled
worker has Creator configuration.  Each known provider is represented without
raw message content or private paths.

The states are deliberately separate:

- `configuration_missing`: optional input is not configured; this is an
  operator action and does not downgrade the core market release.
- `no_event`: the provider completed a scan and returned no new episode.
- `healthy`: sanitized records were accepted for the provider.
- `failed` / `parse_failed`: the provider or parser failed; the issue is
  visible in Mini App source health and cannot become market evidence.

The merge is performed during scheduled snapshot preparation, before release
publication.  It preserves the core source-health rows and only updates the
optional Creator rows, gap counts, and observability counters.  If Creator
configuration is disabled, no Creator rows are added to ordinary market-only
refreshes.  Rollback is safe: remove the scheduled merge and the market source
health contract remains backward compatible.
