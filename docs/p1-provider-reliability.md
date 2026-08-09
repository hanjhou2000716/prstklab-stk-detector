# P1 provider reliability

This change makes public-provider failures explicit and recoverable without
turning a blocked endpoint into a healthy observation.

## Fallback policy

- Binance public spot and kline requests try `api.binance.com`, then
  `api.binance.us` for availability only.
- Binance and Binance.US are the same provider family.  A fallback quote is
  never counted as an independent cross-check; CoinGecko remains the separate
  confirmation source.
- Nasdaq's public endpoint remains the per-index fallback for Stooq's Nasdaq
  and SOX rows.  A fallback is recorded on the quote and source-health row.
- FRED and EIA without their configured keys remain
  `configuration_required`; they are not silently treated as no data.

## Error taxonomy

Provider failures are represented by stable codes such as `http_403`,
`http_429`, `http_5xx`, `timeout`, `invalid_json`, `invalid_payload`, and
`network_error`.  Raw exception messages are not emitted to public JSON or
notifications.  Retryability is recorded so callers can apply bounded retry
without retrying permanent blocks.

## Alert safety

Provider fallback improves availability only.  A source marked partial,
blocked, stale, or unverified cannot satisfy a second-source market gate or
trigger a high-risk alert.  The Mini App should show the provider code and
fallback status in Source Health so an operator can distinguish a degraded
source from an empty event scan.

