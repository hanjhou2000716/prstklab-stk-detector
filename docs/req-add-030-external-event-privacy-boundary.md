# REQ-ADD-030 External event privacy boundary

## Scope

The shared external-event pipeline now applies the same public-only boundary
as the scheduled observation loader and intelligence pipeline. Transport and
private fields such as `message_id`, Gmail identifiers, raw mail bodies,
recipients and local paths are removed recursively before classification,
clustering or evidence output.

Unresolved compound envelopes remain visible as suppressed parser results but
never expose the envelope transport ID as an `observation_id`. Generic records
without a public observation identity no longer fall back to a private Gmail
identifier.

## Verification

- Targeted external-event, observation-loader and intelligence privacy suite:
  **21 passed**.
- Full isolated regression: **1223 passed**.
- Ruff, Mypy and compileall: **pass**.
- The OneDrive-only `os.replace` temporary-file race was reproduced once in a
  full run and the affected build-assets test passed in isolation and in a
  system-temp full run; no production code failure was observed.

## Rollback

Revert the atomic commit. The scheduled observation loader and intelligence
pipeline privacy boundaries remain independently available.
