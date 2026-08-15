# Creator morning batch release binding

The scheduled `morning` lane now passes `--creator-morning-batch` when it
builds the release manifest.  The manifest producer binds the deterministic
10:30 Asia/Taipei Creator cutoff to the exact `market.json.generated_at`
timestamp that is being published.

This keeps one canonical lineage:

```text
sanitized Creator records
  -> scheduled market snapshot
  -> 10:30 morning batch
  -> creator-release.json
  -> release manifest / Release Gate
  -> optional Creator notification
```

Other dashboard refreshes do not enable the flag.  Historical reviewed records
remain visible as public Creator history, but cannot be presented as a current
morning digest.  Missing, stale, or invalid records stay fail-closed and are
not replaced with inferred content.

Rollback: revert this PR.  The manifest remains backward compatible because
the new flag is opt-in and the existing Creator artifact contract is unchanged.
