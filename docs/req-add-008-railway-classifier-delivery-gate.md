# REQ-ADD-008: Railway classifier delivery gate

## Scope

The Railway root-only image can keep its health endpoint alive with a bundled
compatibility classifier when the repository `src` package is not present.
That fallback is not the canonical event-classification contract.

## Behavior

- `src.event_classifier` remains the canonical implementation whenever the
  repository package is available.
- `railway-monitor/app.py` exposes `classifier_delivery_allowed()` so the
  active mode is explicit.
- A root-only compatibility classifier may classify an incoming item for
  diagnostics, but it cannot create a Jin10 repository dispatch.
- The incoming event remains persisted with
  `classification_reason=noncanonical_classifier`, so a later correctly
  packaged deployment can re-evaluate it.
- The health self-check continues to report `classifier_mode` without
  exposing source content or secrets.

This closes the duplicate-classifier delivery risk without deleting the
standalone health fallback or weakening the official-source and market-sync
gates downstream.

## Verification

- `tests/test_railway_monitor.py`: 84 passed, including import isolation and
  the non-canonical delivery gate.
- Full repository regression must be rerun before merge.
- Railway production evidence remains external: deploy a package containing
  the shared `src` classifier and confirm `classifier_mode=repository-shared`
  on `/health` before enabling delivery.

## Rollback

Revert the atomic commit. The previous compatibility classifier behavior
returns, while no schema or persisted data migration is required.
