## Source-health schema and runtime cross-field audit

This stacked PR follows #414 (`feat/p2-source-health-contract`). It turns the
existing source-health state into a publish-time contract without changing the
fail-closed alert policy.

### Changes

- add `schemas/source-health.schema.json` for canonical status, source rows,
  event-scan state, and observability counters;
- add `validate_source_health` to the artifact contract and invoke it for
  complete market source-health envelopes;
- reject contradictory states such as a failed source labelled `no_event` or
  a healthy row carrying stale/partial semantics;
- keep legacy `data_gaps`-only releases readable for backward compatibility;
- document migration and rollback behavior.

### Validation

- `uv run pytest -q --basetemp=.pytest-temp-source-health-2 tests/test_source_health_contract.py tests/test_artifact_contract.py tests/test_runtime_audit.py tests/test_source_health.py tests/test_observability.py` — 38 passed
- `uv run ruff check src/artifact_contract.py tests/test_source_health_contract.py` — passed

### Failure cases covered

- successful empty scan remains `no_event`;
- failed source cannot be hidden by an empty-event label;
- stale/partial semantic state cannot be labelled healthy;
- negative observability counters fail schema validation.

### Rollback

Revert this PR and restore the prior `status=ready` release manifest. Legacy
source-health payloads remain readable; no market or Telegram data is deleted.
