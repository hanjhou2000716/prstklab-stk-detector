# Railway health summary evidence — 2026-08-25

## Requirement mapping

| Requirement | Task | Implementation | Verification | Evidence | Regression | Status |
|---|---|---|---|---|---|---|
| REQ-P0-24-DOD-01 | Distinguish empty scans from source failures | `railway-monitor/health_state.py::summarize_health` | `tests/test_railway_health_state.py`; full suite | local full run: 1423 passed | legacy `status=ok` and health endpoint shape preserved | PASS (local) / NEEDS_REVERIFY (live Railway) |

## Observed contract

- `health_summary.overall_state` is additive and does not replace the legacy
  top-level HTTP reachability field.
- `no_event` / `no_new_content` / `scan_complete` are counted as completed
  empty scans, not failures.
- Configuration missing, not checked, and failed components are counted
  separately.
- Unknown component statuses fail closed as degraded.
- The summary contains only bounded statuses and counters; it excludes
  credentials, message IDs, recipient IDs and raw content.

## Verification evidence

- Targeted Railway monitor/health/external acceptance suite: **112 passed**.
- Full repository regression: **1423 passed**.
- Ruff, compileall and `git diff --check`: **passed**.
- GitHub Actions for PR #766: test-and-dry-run, CodeQL, dependency review and
  SBOM: **passed**.

Live Railway endpoint and Pages browser evidence remain an external acceptance
step; this PR does not claim that production has been reverified.
