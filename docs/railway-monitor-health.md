# Railway monitor health semantics

The Railway monitor keeps polling and serving `/health` even when an optional
observability callback is unavailable. The callback posts a bounded GDELT
diagnostic to the repository dispatch API; it is not the source of truth for
market data or Telegram delivery.

## GitHub dispatch status

The `/health` payload distinguishes the callback failure from the provider:

- `healthy`: the repository dispatch was accepted.
- `configuration_missing`: `GITHUB_DISPATCH_TOKEN` or `GITHUB_REPOSITORY` is
  not configured, or GitHub returned 401.
- `permission_denied`: GitHub returned 403. The token exists but cannot create
  repository dispatches (for example, it lacks Actions/repository permission).
- `degraded`: a transient network, 429, or 5xx failure occurred.

401/403 responses enter a bounded 15-minute backoff. This prevents a bad token
from generating a request and warning every poll cycle. The payload includes
`health_dispatch_next_retry_at`; local Railway health and delivery receipts
remain authoritative while the callback is paused. Fix the token permission or
repository name, then wait for the next retry window or restart the service.

## GDELT rate limiting

GDELT is a discovery source and is subject to public rate limits. A 429 uses
`Retry-After` (or bounded exponential backoff) and may use a cache no older
than the configured stale window. When that happens the health payload reports
`status=fallback_active`, `stale_cache_used=true`, and the safe error label
(`HTTP_429`). Cached headlines remain visible for investigation, but they are
not eligible to create a new Telegram alert until a live fetch succeeds.

This is intentionally fail-closed: a GDELT outage cannot be interpreted as a
live confirmation, and it cannot block Jin10 polling or existing delivery
receipts.
