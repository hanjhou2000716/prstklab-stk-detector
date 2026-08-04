# P0-07: Reproducible CI and supply-chain checks

The repository now has a `pyproject.toml` and committed `uv.lock`. CI installs the existing requirements for compatibility, then runs `uv sync --locked --all-groups` so the test environment is reproducible. Python tests emit coverage XML and terminal coverage; the new release tooling is required to pass Ruff and mypy.

`security.yml` adds three independent checks:

- Dependency Review blocks high-severity dependency changes on pull requests.
- CodeQL scans Python without requiring a build step.
- Anchore emits a CycloneDX SBOM artifact for every main/PR/scheduled run.

The quality and security workflows pin their Actions to immutable commit SHAs. Existing operational workflows are migrated in subsequent maintenance work; do not introduce new tag-based Actions.

## Rollback

If a lock update breaks CI, revert the commit containing `uv.lock` and `pyproject.toml`; the quality workflow still has the compatibility `requirements.txt` install line. Security checks can be rerun independently and do not publish or send notifications.

## Known baseline

The older source tree contains pre-existing Ruff findings outside the new release tooling. P0-07 fails on new P0-07 modules while reporting the broader cleanup as a follow-up debt item; tightening the full-tree threshold requires a separate mechanical formatting PR.