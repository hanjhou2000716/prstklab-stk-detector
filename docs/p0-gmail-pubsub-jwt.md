# Gmail Pub/Sub JWT verification

Railway can run the Gmail push gateway in strict mode with
`GMAIL_PUBSUB_REQUIRE_JWT=true`. In that mode `GmailIngressService` requires an
injected verifier to validate the bearer token signature, issuer, audience, and
service-account subject. Header presence alone is not accepted.

The repository deliberately does not implement a private key or Google token
exchange. The Railway transport adapter must provide the verifier using the
official Google library and its managed key cache. Missing, expired, or
audience-mismatched tokens fail closed with `pubsub_jwt_verification_failed`.
For local fixtures strict mode can be tested with a deterministic verifier
callback; no real token or credential is committed.

Rollback is additive: leave strict mode disabled for legacy development
fixtures, or revert the adapter commit. Production should enable strict mode
after the Railway verifier is configured.
