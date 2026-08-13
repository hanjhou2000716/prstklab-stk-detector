# P0-04 release manifest integrity

Release validation now rejects artifact paths that are absolute or escape the
release root. A rollback manifest must explicitly identify the previous
successful `rollback_release_id`; a ready manifest cannot carry rollback state.
The existing required artifact hashes, snapshot IDs and status schema remain
unchanged.

Verification: 73 release-manifest, release-gate and artifact-contract tests
passed, compilation and diff checks passed.

Rollback: revert this PR to restore the prior manifest validator; no release
data is deleted and the Pages release gate remains available.
