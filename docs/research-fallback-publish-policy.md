# Research fallback publication policy

The scheduled brief, official event monitor, emergency alert, Railway monitor
health sidecar, and manual dashboard refresh may publish a market/event
snapshot while a bounded research scan is incomplete.
They must opt in to the manifest builder's stale-research fallback and provide
an explicit reason.

The builder rewrites the research artifact before hashing the release with:

- `publication_state: fallback`
- `research_fallback_used: true`
- `availability: expired`
- `production_eligible: false`
- blocked source states (`scan_state=failed`, `candidate_state=data_gap`)

This keeps market, research, and event artifacts in one immutable release and
lets the Mini App show market data with a degraded-research banner. It never
makes research candidates eligible and cannot authorize a high-risk event
without independent source evidence.

The emergency and health sidecar paths use the same explicit fallback contract;
an incomplete research scan therefore cannot turn an otherwise valid market or
official-event publication into a workflow-wide failure. The release gate still
rejects an invalid manifest, missing source evidence, or an unverified
high-risk event.

The unified research workflow remains the only path that can publish a fresh
production research snapshot. Its full-universe acceptance checks are not
relaxed by this fallback.

Rollback: restore the previous successful `data-release` commit and redeploy
its ready manifest. Do not edit public JSON by hand.
