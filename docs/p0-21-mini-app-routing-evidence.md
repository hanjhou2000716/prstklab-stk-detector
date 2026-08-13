# P0-21 Mini App release/deep-link evidence

The router requires an exact release ID before exposing an alert. Snapshot and
observation identities are checked against the manifest and alert. A retired
release returns an archive state, and an unknown alert returns a missing state;
neither falls through to a different current event. The browser loader keeps
the existing retry/last-good-release behavior and does not mix artifact
versions.

Rollback is the atomic commit revert; the existing Mini App remains available.
