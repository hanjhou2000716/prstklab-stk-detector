# P0-06 safe data publishing evidence

## Scope

Generated market, event, health, and research artifacts are published to the
dedicated `data-release` branch. Application code and workflow definitions stay
on `main`; no high-frequency workflow is allowed to push generated files to
`main`.

## Contract and implementation

- `src/data_release.py` accepts only `site/data/**` or explicitly selected
  `data/**` paths, rejects traversal and absolute paths, and stages through a
  temporary `GIT_INDEX_FILE`.
- Existing `data-release` history is loaded before a partial publisher writes a
  tree, preventing one workflow from deleting another workflow's cache.
- The commit is created with `git commit-tree` and pushed only to
  `refs/heads/data-release`.
- All six data publishers use the shared `main-data-writer` concurrency group,
  restore before refresh, and publish with `DATA_RELEASE_BRANCH`.
- Pages explicitly refreshes and restores `origin/data-release`, rejects an
  invalid manifest, and runs the release gate before upload.

## Verification

The contract tests assert path restrictions, isolated-index publishing,
serialized writers, absence of `HEAD:main` pushes, and Pages restore-before-
validation. Runtime tests in `tests/test_data_release.py` cover empty releases,
missing remote cache paths, parent-tree preservation, and ignored artifact
staging.

## Rollback

Do not merge generated data into `main`. To roll back, select a known-good
`data-release` commit, restore that ref in a controlled Pages run, and rerun the
release gate. If the branch is unavailable, publishers fail closed or bootstrap
only the selected public data paths; Telegram delivery remains gated by a
successful published release.

## Traceability

- Requirement: P0-06 safe data publishing
- DoD: generated data does not pollute `main`; release branch is serialized,
  path-restricted, restorable, and rollbackable
- Evidence: `tests/test_safe_data_publishing_contract.py`,
  `tests/test_data_release.py`, workflow source, and CI logs for this PR
- Regression: preserve release manifest, Pages release gate, and publish-before-
  notify behavior from P0-04/P0-05
