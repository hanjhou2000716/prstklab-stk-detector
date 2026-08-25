# Immutable data-release writer ordering

The public snapshot branch is an append-only data channel shared by the market
refresh, scheduled brief, official-event, emergency-alert, monitor-health and
unified research workflows. Every workflow that publishes to that branch uses
the same GitHub Actions concurrency group: `main-data-writer`.

The group is non-cancelling, so a later run waits for the current writer to
finish instead of interrupting a release between restore, validation, publish
and Pages deployment. This prevents two workflows from reading the same parent
commit and then racing `git commit-tree`/push, which could otherwise yield a
non-fast-forward failure or a snapshot composed from different observations.

The repository test `test_all_data_release_publishers_share_one_concurrency_group`
scans every publisher workflow. Adding a new data-release writer without the
shared lock fails CI. A failed writer remains fail-closed: it does not send a
Telegram notification for an unpublished release, and the previous immutable
release remains the rollback target.

## Partial publish preservation

Writers are allowed to publish different subsets of the public tree. For
example, a market refresh publishes `site/data`, while the research workflow
also publishes the MOPS and SEC checkpoint caches under `data/`. The publisher
therefore seeds its temporary Git index from the current `data-release` parent
before staging the requested paths. A partial writer updates only its selected
artifacts and carries every other artifact forward; it must never turn a
market-only refresh into a cache deletion. This is covered by
`test_publish_stages_on_existing_release_tree`.

## Non-mutating restore drill

Use `python -m src.data_release --restore --dry-run` to inspect the latest
`data-release` tree without checking files out or changing the working tree.
The result reports `planned_files` and `missing_remote`; only an explicit
restore without `--dry-run` may modify the checkout.
