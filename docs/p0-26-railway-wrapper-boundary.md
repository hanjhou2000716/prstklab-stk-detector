# P0-26 Railway wrapper boundary

## Problem

`railway-monitor/app.py` had a second, unreachable implementation after several
delegating returns.  The running monitor already used the extracted store and
health modules, but the dead SQL/HTTP copies made ownership ambiguous and could
become active again during a later edit.  This increased the risk of different
behaviour between the Railway process and direct module tests.

## Change

The compatibility methods and public health-dispatch function remain in
`app.py`, but now contain only their delegated implementation.  The canonical
logic stays in the extracted modules:

- `delivery_store.py` for history, diagnostics and retention;
- `ledger_store.py` for event cooldown, observation and reminder state;
- `health_dispatch.py` for bounded GitHub dispatch retry/backoff and non-fatal
  401/403/429 handling.

The `timedelta` import remains intentionally available because the monitor
module is a compatibility surface used by existing stale-cache tests.

## Verification

```text
tests/test_railway_monitor.py
tests/test_railway_health_dispatch.py
tests/test_railway_delivery_store.py
96 passed
python -m compileall -q railway-monitor
git diff --check
```

The public wrapper names and stale-cache behaviour are unchanged.  No Railway
secret, callback, source policy or delivery gate was modified.

## Rollback

Revert this PR.  The extracted modules remain unchanged, so rollback restores
the previous wrapper file without changing persisted Railway data.
