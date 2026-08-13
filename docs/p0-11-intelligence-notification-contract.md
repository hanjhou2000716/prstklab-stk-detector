# P0-11 Intelligence notification identity contract

## Scope

The intelligence contract now validates the same `notification_id` used by the
alert envelope, budget and event ledger. Every unsuppressed unified external
event must carry a non-empty identity. Suppressed parse failures remain visible
without an identity because they are intentionally not eligible for delivery.

## Evidence

- Targeted contract, pipeline and external-event regression tests: 16 passed.
- Python compilation and `git diff --check` passed locally.
- PR #571 provides the upstream alert-envelope identity contract and CI evidence.

## Rollback

Revert this PR to remove the intelligence-level validation. The upstream alert,
budget and ledger identity contracts remain independently reversible.
