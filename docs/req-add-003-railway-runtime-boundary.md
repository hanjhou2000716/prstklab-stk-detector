# P0-26 Railway runtime boundary (incremental)

This task isolates the Railway monitor's environment configuration lookup from
the large HTTP/event service module.  The standalone deployment can import
`railway-monitor/runtime_config.py` without importing repository `src`, while
the existing `_delivery_shared_secret()` compatibility wrapper remains in
`app.py` for current callers.

## Contract

- `DELIVERY_STATUS_SHARED_SECRET` remains the active Railway service name.
- `RAILWAY_STATUS_SHARED_SECRET` is the Actions-facing fallback during migration.
- Missing or blank values produce `configuration_missing` and fail closed.
- Health metadata contains booleans and status only; secret values are never
  returned, logged, or serialized.

## Verification

`tests/test_railway_runtime_config.py` covers the preserved precedence,
compatibility, missing configuration, blank values, and secret redaction. The
remainder of the broader Railway architecture cleanup (further extraction of
the event/HTTP service and live Railway acceptance) remains
`NEEDS_REVERIFY`/external and is not claimed by this incremental task.

## Rollback

Revert this atomic commit.  The compatibility wrapper in `app.py` preserves
the previous environment lookup behavior if the boundary is removed.

