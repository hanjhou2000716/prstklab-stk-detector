# Creator release artifact publication

When a creator artifact is supplied to `build_release_manifest`, it is written
as `data/creator-release.json` and included in the manifest's artifact paths
and hashes. The artifact remains additive: a validation mismatch marks the
creator status unavailable without invalidating the parent market release.
Consumers must use the manifest path and hash; they must not combine an
unbound creator file with a different market/event release.
