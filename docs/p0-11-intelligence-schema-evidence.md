# P0-11 Intelligence schema evidence

The intelligence JSON Schema now mirrors the runtime notification identity
contract: every unsuppressed unified external event declares a
`notification_id`; a suppressed parse failure may remain identity-free while
remaining visible and non-deliverable.

Verification: 13 targeted schema/contract/pipeline tests passed, Python
compilation passed, and `git diff --check` passed.

Rollback: revert this PR to restore the previous permissive intelligence
schema; the alert, budget and ledger contracts remain independently guarded.
