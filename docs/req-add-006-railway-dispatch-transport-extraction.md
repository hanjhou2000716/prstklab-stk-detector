# REQ-ADD-006 — Railway dispatch transport extraction

This slice extracts only the bounded GitHub repository-dispatch HTTP
transport from `railway-monitor/app.py`. Event classification, signing,
outbox persistence and the poll loop remain owned by the existing monitor;
there is no second classifier or notification path.

## Contract

- Three attempts maximum with bounded exponential backoff.
- Honour a bounded `retry_after` value for HTTP 429 responses.
- Retry transient HTTP errors and 5xx responses.
- Preserve non-retryable HTTP errors for the caller.
- Log only the trace ID and error class; never payloads or secrets.

## Verification

`tests/test_railway_dispatch_transport.py` covers 429 and connection-error
recovery using an injectable HTTP client. The compatibility wrapper in
`app.py` continues to be the production entry point, so existing monitor and
outbox tests exercise the same behavior.

## Rollback

Revert the extraction commit. The legacy transport body can be restored
without changing event schema, signing, persistence, or dispatch policy.
