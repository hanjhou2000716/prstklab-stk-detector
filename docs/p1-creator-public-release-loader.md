# P1 Creator public release loader

Creator Intelligence is an optional artifact in a release, but it is not an
independent snapshot. When `release-manifest.json` advertises
`creator-release.json`, the release gate and Mini App both verify its SHA-256
hash and bind these fields to the parent release:

- `parent_release_id`
- `market_snapshot_id`
- `event_snapshot_id`
- `creator_release_id` (when declared by the manifest)

The Mini App only attaches the verified artifact to the current market
snapshot. A malformed or mismatched creator artifact is never substituted
from another release; the loader falls back to the last verified release or
shows the normal degraded state. A creator artifact marked unavailable is
displayed as unavailable without blocking the core market release.

Rollback is safe: remove the optional creator artifact declaration from the
next manifest, or publish the previous release manifest. Core market,
research and event artifacts remain unchanged.
