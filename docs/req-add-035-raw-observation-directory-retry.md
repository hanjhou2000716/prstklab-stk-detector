# REQ-ADD-035 — raw observation directory-race retry

## Root cause

The raw observation writer retried the final atomic replace but not the
temporary payload write. On a OneDrive-backed checkout, a sync/indexing race
can briefly remove the dated provider directory between `mkdir` and
`write_bytes`, producing `FileNotFoundError` and marking the observation
unavailable.

## Fix

`write_bytes_with_retry` recreates the parent directory and retries bounded
transient `ENOENT`/permission/lock errors before the existing atomic replace.
Non-retryable errors remain fail-closed.

## Verification

- Directory removal during the first write is covered by
  `test_raw_store_recreates_directory_after_transient_sync_race`.
- Raw observation, market snapshot, refresh and source-adapter persistence
  suites pass on the merged main worktree.

## Rollback

Revert the atomic commit. This only changes bounded local persistence retries;
it does not alter release, notification or source-quality gates.
