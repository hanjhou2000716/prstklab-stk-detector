# REQ-ADD-033 publish-lock regression evidence

The first full regression after the Railway import fix reproduced a separate
Windows/OneDrive `PermissionError` in `src/build_assets.py` while replacing
`site/index.html`. This is a real publish-path failure, not a flaky test to
ignore.

The bounded retry contract is centralized in `src/atomic_file.py` and is used
by raw observations, asset manifests, market snapshots, and release manifests.
Non-retryable errors still fail closed.

Verification:

- transient replacement-lock fixture for `build_assets`
- targeted build/raw/refresh/release/Gmail suite
- full repository regression must pass before REQ-ADD-033 is marked PASS

Rollback: revert the atomic commit for this task. The canonical registry import
remains available from the repository-level `src` package on a full checkout.
