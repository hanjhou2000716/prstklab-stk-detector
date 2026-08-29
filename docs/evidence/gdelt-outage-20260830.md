# GDELT outage and bounded fallback evidence — 2026-08-30

At 2026-08-30 (Asia/Taipei), a single low-load read-only request to the
configured GDELT DOC endpoint (`query=Taiwan`, `maxrecords=1`) timed out after
15 seconds. A retry from the external-acceptance path likewise reported the
provider as unavailable; no article or market direction was inferred.

The production monitor therefore remains fail-closed:

- the provider is exposed as `failed`/unavailable rather than `no_event`;
- the existing bounded cache and persisted backoff are used when a recent
  success exists;
- stale fallback data cannot qualify a high-risk alert;
- no Telegram, Railway, or configuration side effect occurred.

The bounded 429/invalid-response fallback and restart-cooldown behavior remain
covered by `tests/test_railway_monitor.py` and the full repository suite. This
evidence records an upstream outage, not a claim that GDELT recovered; a later
scheduled poll should re-verify provider availability.
