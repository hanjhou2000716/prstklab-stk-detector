# External acceptance gate summary

`src.external_acceptance` is a read-only probe for the live Railway and Pages
boundaries.  It now emits a `gate_summary` alongside the existing overall
`PASS`/`NEEDS_REVERIFY` result.  The summary is derived from the same blocking
reasons, so it cannot turn an unsafe release into an accepted one.

The gates are:

- `railway_health`: the health endpoint was reachable and did not report a
  blocking Railway state;
- `gmail_watch`: Gmail ingress/watch state was checked and is healthy (or the
  probe explicitly records `not_checked`);
- `delivery_receipt`: a delivery receipt was observed and its persistence was
  durable; `not_checked` is not a failure, but it is not delivery evidence;
- `pages_manifest`: the public manifest is HTTP 200 and `status=ready`;
- `pages_artifacts`: every declared artifact hash and snapshot binding passed.

Each gate has one of:

- `pass` — the gate was checked and passed;
- `needs_reverify` — a checked gate has a bounded failure or mismatch;
- `not_checked` — the probe did not have enough evidence to make a claim.

This distinction is intentionally conservative.  A missing optional provider
is not reported as “no risk”, and an unexercised delivery lane is not reported
as delivered.  The command remains read-only and never changes Railway,
Google Cloud, Pages, Telegram, or repository state.

Example (redacted):

```json
{
  "schema_version": "1.0",
  "status": "NEEDS_REVERIFY",
  "gate_summary": {
    "railway_health": {"status": "pass", "blocking_reasons": []},
    "gmail_watch": {"status": "needs_reverify", "blocking_reasons": ["railway_gmail_watch:failed"]},
    "delivery_receipt": {"status": "not_checked", "blocking_reasons": []},
    "pages_manifest": {"status": "pass", "blocking_reasons": []},
    "pages_artifacts": {"status": "pass", "blocking_reasons": []}
  }
}
```

Use `--fail-on-needs-reverify` in CI or an acceptance run when a live PASS is
required.  Do not treat an offline/mock run as evidence of production delivery.
