# P0-08 source health and data-gap evidence

## Contract

Source health distinguishes a successful scan with no matching event from a
provider or parser failure. `event_scan.status=no_event` is only emitted when
required dependencies are healthy; a required source failure produces
`scan_failed` and remains visible as a runtime gap. Optional missing credentials
are reported separately as `configuration_missing` and do not masquerade as a
market outage.

The aggregate envelope keeps `missing_source_count`,
`runtime_failure_count`, and `configuration_missing_count` consistent with
the per-source semantic states. The artifact validator rejects mismatched
counters and contradictory status/semantic-state pairs.

## Verification

`tests/test_p0_08_source_health_contract.py` covers clean no-event scans,
required-source failures, optional configuration gaps, counter consistency,
and schema validation. Existing source-health tests cover research warming,
stale data, fallback, GDELT pending confirmation, and per-provider failure
details.

## Rollback and preservation

Revert the P0-08 atomic test/evidence commit only if it is necessary; preserve
the existing source-health producer and fail-closed release gate. A rollback
must not collapse `no_event` and `scan_failed`, because that would hide a data
outage and violate the notification safety boundary.

## Traceability

- Requirement: P0-08 source health and data gaps
- DoD: clean scans, failures, stale/fallback, and configuration gaps are
  distinct, counted, and validated
- Evidence: targeted tests, existing source-health suite, and PR CI
