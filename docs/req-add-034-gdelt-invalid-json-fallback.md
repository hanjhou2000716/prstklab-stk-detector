# REQ-ADD-034 — GDELT invalid JSON fallback

GDELT is a discovery source and may return an HTML/proxy error body with HTTP
200. The monitor now parses and validates the payload inside the guarded fetch
boundary. A malformed response is classified as `invalid_json` or
`invalid_payload`, uses the recent bounded cache when available, and is never
marked `live` or promoted to a high-risk alert.

Verification:

- `tests/test_railway_monitor.py` targeted suite: 86 passed
- full repository regression: 1227 passed
- Ruff: pass

Rollback: revert the atomic commit for this task. The existing GDELT backoff,
trusted-domain, cross-check, and event-ledger gates remain unchanged.
