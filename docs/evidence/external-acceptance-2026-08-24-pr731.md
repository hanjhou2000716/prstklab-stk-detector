# External acceptance evidence — PR #731 — 2026-08-24

This capture was run with the read-only external-acceptance workflow from
`fix/railway-gmail-gdelt-runtime-resilience`. It did not write Railway state,
publish Pages, or send Telegram.

## Result

- Overall: `NEEDS_REVERIFY`
- Pages: HTTP 200; manifest `ready`; five artifact hashes verified; no snapshot
  mismatch.
- Railway monitor: HTTP 200; service `running`; heartbeat `healthy`; Jin10
  `healthy`.
- GDELT: `failed`, error `invalid_json`; no stale cache was used.
- Gmail: `failed`, redacted error `GmailIngressError`; watch remained active and
  no required configuration field was missing.
- Delivery side effects: Telegram `false`; Railway write `false`;
  configuration changed `false`.

The two source failures are deliberately retained as source-health failures;
they do not qualify for high-risk notification. After PR #731 is merged and
Railway restarts with the updated bundle, rerun the same read-only workflow.
Only a fresh capture with both source contracts healthy (or an explicit,
well-formed no-content state) may move P0-12/P0-24/P0-26/P0-27 to PASS.

