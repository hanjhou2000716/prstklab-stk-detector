# P1-05 Railway health contract

`src/railway_health_contract.py` converts the private Railway monitor payload
into a bounded, non-secret health record. It distinguishes an operator
configuration error (HTTP 401/403), a retryable provider limit (429/5xx), and
an old or missing heartbeat. No raw exception text, token, URL query or secret
is copied into the public record.

`restart_recommended` is only true for a failed/stale worker. A 403 is surfaced
as `configuration_missing` so an operator can fix the shared secret or URL
without causing a restart loop. A 429 remains `degraded` with a retry hint
bounded to one hour.

## Rollback

Revert this additive contract and its tests. Existing Railway `/health`
diagnostics remain unchanged; no delivery decision is weakened.
