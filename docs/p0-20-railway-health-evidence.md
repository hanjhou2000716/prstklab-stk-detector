# P0-20 Railway health evidence

Railway health normalization treats 401/403 and missing configuration as an
operator configuration state, not a restart command.  429, 5xx, timeout and
network errors are retryable degraded states with a retry hint bounded to one
hour.  A genuinely stale or failed heartbeat remains explicit and can request
restart.  Normalized payloads never include secrets or raw exception text.

The contract suite extends the existing monitor and health tests.  Rollback is
the atomic commit revert; the existing Railway endpoint remains available.
