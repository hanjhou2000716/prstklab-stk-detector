# P0-07: Reproducible CI and supply-chain checks

The repository now has a `pyproject.toml` and committed `uv.lock`. CI installs the existing requirements for compatibility, then runs `uv sync --locked --all-groups` so the test environment is reproducible. Each run first erases prior coverage files, then emits coverage XML and terminal coverage. The full-tree report is currently informational (`--cov-fail-under=0`) because legacy modules are below the eventual threshold; Ruff and mypy remain blocking checks for the new release tooling.

`security.yml` adds three independent checks:

- Dependency Review blocks high-severity dependency changes on pull requests.
- CodeQL scans Python without requiring a build step.
- Anchore emits a CycloneDX SBOM artifact for every main/PR/scheduled run.

The quality and security workflows pin their Actions to immutable commit SHAs. Existing operational workflows are migrated in subsequent maintenance work; do not introduce new tag-based Actions.

## Rollback

If a lock update breaks CI, revert the commit containing `uv.lock` and `pyproject.toml`; the quality workflow still has the compatibility `requirements.txt` install line. Security checks can be rerun independently and do not publish or send notifications.

## Known baseline

The older source tree contains pre-existing Ruff findings outside the new release tooling. P0-07 reports the broader coverage and lint cleanup as follow-up debt; tightening the full-tree threshold requires dedicated coverage and mechanical-formatting PRs. The coverage reset and subprocess isolation prevent stale or incompatible data files from making an otherwise passing test run fail.
