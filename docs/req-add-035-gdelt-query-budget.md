# GDELT query budget and bounded discovery

## Root cause

The repository keyword bundle intentionally contains a large Traditional
Chinese/English vocabulary. Sending that full expression to GDELT, then
appending additional oil and Gulf terms, can exceed the discovery endpoint's
Boolean-query budget. GDELT may return an HTML error page with HTTP 200 in that
case; treating it as JSON produces `invalid_json` and wastes the retry window.

## Canonical fix

`railway-monitor/app.py` keeps the full keyword database for local semantic
classification, but bounds the provider query with `bounded_gdelt_query()`.
Overlong configured or environment-provided queries use a curated 900-character
discovery expression that preserves the highest-value macro, conflict, energy,
technology and Chinese anchor terms. A provider rate limit still remains an
explicit failed/degraded source state and cannot qualify a high-risk alert.

## Verification

- 28 GDELT monitor tests and 99 Railway/GDELT regression tests pass.
- A local request using the compact query reached GDELT's rate-limit response;
  this confirms the query is accepted by the endpoint and that the remaining
  failure is external throttling, not an overlong expression.
- Existing bounded backoff and two-hour stale-cache rules remain unchanged.

## Rollback

Revert the atomic query-budget commit. The previous fail-closed behavior is
restored; no public release or notification data is changed by this document
or the query builder.
