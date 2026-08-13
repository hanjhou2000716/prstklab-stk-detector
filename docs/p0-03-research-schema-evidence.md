# P0-03 research candidate-state schema

The research report schema now enforces the distinction between a complete
empty scan and a partial scan with available completed records. A complete
`no_candidates` source must expose zero visible candidates; an available source
must expose at least one; a `building` source may expose partial candidates and
history-pending counts.

Verification: 36 research-state, artifact-contract and integration tests
passed, compilation and diff checks passed.

Rollback: revert this PR to restore the previous permissive schema. Runtime
research state generation and its fail-closed source-failure behavior remain
unchanged.
