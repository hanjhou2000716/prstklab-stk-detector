# Partial research candidate state

The Taiwan MOPS history build is intentionally incremental. A run can have
validated records and formal candidates while the remaining historical universe
is still pending. The producer now reports:

- `available`: complete universe and candidates;
- `available_from_completed_records`: candidates are valid for completed
  records, while the universe remains `building` or `partial`;
- `data_gap`: no candidate can be evaluated because required data is missing;
- `no_candidates`: the scan completed with no qualifying rows.

This is a display-contract correction, not a screening relaxation. Incomplete
companies remain excluded, and the research publication gate still prevents a
partial run from becoming a fresh production research release.

## Rollback

Revert this PR to restore the previous summary label. No persisted data or
secret migration is required.
