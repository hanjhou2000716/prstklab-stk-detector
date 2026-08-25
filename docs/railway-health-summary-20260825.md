# Railway health summary contract

The monitor keeps the legacy top-level `status=ok` as an HTTP reachability
signal.  It now also publishes an additive `health_summary` object so operators
can distinguish service availability from source semantics:

- `healthy`: all checked components are healthy or completed an empty scan.
- `partial`: at least one component is healthy/no-event while another is
  failed, stale, not checked, or missing configuration.
- `configuration_missing`: no component has a runtime failure, but required
  configuration is absent.
- `not_checked`: the monitor has not completed a source check yet.
- `failed`: every checked component is failed or otherwise unknown.

The summary includes component status, counts for no-event, configuration
missing, not-checked and failure states.  `no_event` / `no_new_content` and
`scan_complete` never increase the failure count.  Unknown statuses are
treated as degraded so a new provider state cannot silently appear healthy.
No credentials, message IDs, recipient IDs or raw email content are included.

## Verification

`tests/test_railway_health_state.py` covers mixed, all-empty and detached
snapshot behavior.  The existing monitor health tests remain unchanged; the
legacy reachability field is preserved for backwards compatibility.

## Rollback

Revert this atomic change.  It is additive, requires no migration, and does not
change release or Telegram eligibility decisions.
