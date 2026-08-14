# REQ-ADD-004 — Railway health contract extraction

## Scope

This is a bounded continuation of the Railway architecture cleanup described
in the Creator Intelligence V2 prompt.  It extracts the provider-independent
health calculations from `railway-monitor/app.py` into the standalone
`railway-monitor/health_contract.py` deployment module:

- counter and timestamp parsing;
- poll-loop heartbeat status;
- health-route path normalization; and
- privacy-safe Gmail health projection.

The monitor keeps compatibility wrappers, so existing callers and the
standalone Railway root layout continue to work.  The module imports only the
Python standard library and cannot accidentally import the repository `src`
package.

## Safety boundary

This task does not change alert qualification, source consensus, release
gates, Telegram delivery, or secret values.  Malformed counters and timestamps
remain fail-closed, and Gmail transport cursors are not projected into the
public health response.

## Verification

- `tests/test_railway_health_contract_standalone.py` covers the standalone
  module without repository imports.
- `tests/test_railway_monitor.py` preserves the legacy app-level API and
  standalone import smoke test.
- Targeted result: 93 passed.
- Ruff and Mypy pass for the extracted module and tests.
- `python -m compileall -q railway-monitor` passes.

## Rollback

Revert the atomic extraction commit.  The app compatibility wrappers keep the
previous call surface, so rollback does not require a data migration.

## Remaining work

Email routing, persistence, dispatch and the full poll loop remain separate
bounded extraction tasks.  Live Railway health and delivery receipts remain
external acceptance evidence and are not claimed by this local contract.

