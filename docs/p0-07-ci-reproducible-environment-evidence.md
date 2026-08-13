# P0-07 CI and reproducible environment evidence

## Contract

- Python dependencies are declared in `pyproject.toml` and resolved by the
  checked-in `uv.lock`; CI uses `uv sync --locked --all-groups`.
- The quality workflow runs the full test suite, project coverage floor (80%),
  core release/delivery coverage floor (90%), Ruff, Mypy, compileall, artifact
  audit, delivery smoke, and offline release-to-delivery acceptance.
- Every external GitHub Action in workflows and local actions is pinned to a
  full commit SHA. Mutable tags are rejected by the contract test.
- Security CI retains dependency review, CodeQL, and SBOM generation with a
  truthful deterministic fallback when the SBOM tool is unavailable.

## Verification

`tests/test_p0_07_ci_contract.py` checks the lockfile and quality gates, scans
all workflow YAML for immutable action references, and verifies supply-chain
jobs. Existing CI tests retain coverage and security regression checks.

## Rollback

Revert the P0-07 atomic commit to remove only the new contract/evidence tests.
Do not remove the lockfile or weaken existing CI gates; a rollback that cannot
preserve locked dependencies and security checks must be treated as blocked.

## Traceability

- Requirement: P0-07 hardened CI and reproducible environment
- DoD: locked dependency resolution, full quality gates, SHA-pinned actions,
  supply-chain analysis, and evidence-backed regression checks
- Preservation: P0-01 through P0-06 release, schema, publication, and
  fail-closed behavior remain unchanged
