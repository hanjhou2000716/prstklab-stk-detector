# REQ-ADD-025 - Mini App health baseline labels

## Scope

Project the explicit Railway baseline states into the source-health rows. A
provider that has not run yet (`not_checked`, `not_scanned`, or
`not_checked_yet`) must be shown as **尚未檢查**, not as a data gap or a scan
failure. This preserves the distinction between a preflight state, a clean
empty scan, and a failed scan.

## Implementation

- `site/app.js` normalizes the state once and maps all three baseline aliases to
  the same investor-facing label.
- Existing failure, stale, fallback, pending, and no-event mappings remain
  unchanged.
- `tests/test_mini_app_layout.py` asserts that the baseline aliases and label
  remain present in the browser bundle.

## Verification

- `python -m pytest -q tests/test_mini_app_layout.py` -> `27 passed`.
- `node --check site/app.js` -> pass.
- `tests/test_mini_app_browser_contract.py` -> skipped locally because the
  local Chromium binary is unavailable; CI provisions the browser and remains
  the required browser evidence.

## Safety and rollback

This is a UI-only additive mapping. Reverting the commit restores the previous
generic label and does not alter release gates, source counts, or alert
eligibility. No data, secret, or production recipient is changed.

