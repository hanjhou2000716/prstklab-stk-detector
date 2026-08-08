# Source health reliability

Provider health is intentionally separate from the legacy `status` field. The
legacy value remains available to older consumers, while `health_class` is the
actionable classification used by release and alert gates.

| `health_class` | Meaning | Alert/research behavior |
| --- | --- | --- |
| `healthy` | Required provider returned complete data. | May participate in a confirmation gate. |
| `degraded_with_fallback` | Primary provider failed but an independent fallback returned data. | Data remains visible; it is not equivalent to a confirmed primary quote. |
| `optional_degraded` | An optional provider is partial or stale. | Keep the card visible and expose the gap; do not treat it as evidence. |
| `configuration_required` | A required credential or setting is missing. | Fail closed until configuration is supplied. |
| `critical_gap` | A core, alert, or research provider failed without an acceptable fallback. | Do not trigger a high-risk alert or publish a complete claim. |
| `failed` | An optional provider failed without usable data. | Record the failure and continue independent providers. |

Every health object also carries `required_for`, `fallback_active`,
`provider_status`, `checked_at`, and an explicit `data_gap`. A fallback is
never silently relabelled as the primary source. The crypto adapter reports
primary/secondary record counts; the public-market secondary adapter reports
when Nasdaq was used for a symbol that Stooq could not provide.

## Operational rules

1. Missing FRED/EIA keys are `configuration_required`, not generic partial
   success.
2. FRED is required for research context; EIA is required for alert evidence.
3. Binance/CoinGecko and Stooq/Nasdaq are independently isolated. One provider
   failure must not hide successful cards from the other provider.
4. `critical_gap` and `configuration_required` block confirmation and
   escalation. They do not mean that the market is safe or that no event
   exists.
5. UI/source-health consumers should show the class and the gap reason, while
   keeping the underlying quote card visible when a validated fallback exists.

The classification is covered by provider-level tests and is deliberately
fail-closed for required paths.
