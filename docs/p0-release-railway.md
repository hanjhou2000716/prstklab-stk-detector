# P0 release and Railway safeguards

This change makes data publication fail closed without losing the evidence
needed to diagnose a bad source.

## Release contract

`src.release_manifest` normalizes only legacy representation defects before it
computes hashes: provider labels are reconciled with an unambiguous source
domain, stale technical context is explicitly marked, research candidate state
is derived from machine fields, dictionary gap counts are reduced to an
integer, and missing research/event snapshot IDs are deterministic.  It never
creates a quote, candidate, timestamp, or confirmation.  Remaining contract
errors keep the manifest `invalid`, so the publish workflow cannot send a
Telegram notification for that release.

## Data-release git identity

`src.data_release.publish` supplies an explicit non-secret Git identity to
`git commit-tree`, using repository configuration, `GIT_AUTHOR_*`, the GitHub
actor, or the standard Actions bot fallback.  A failed commit now reports the
sanitized git error instead of returning an opaque exit 128.

## Railway degradation policy

GDELT HTTP 429 responses honor `Retry-After`, apply bounded exponential
backoff, and use the last successful cache when it is inside the configured
stale window.  GitHub monitor-health callbacks treat 401/403 and exhausted
429/5xx retries as an observability degradation; they do not crash the source
poller or spin on a forbidden token.  Local Railway health remains the source
of truth.  Alert dispatches still fail closed and remain durable/retryable.

## Rollback

Revert this PR and redeploy the previous commit.  No database migration is
required.  The normal data-release branch and its previous commit remain
available for release rollback.
