# Production acceptance evidence — 2026-08-20

This record captures the approved `refresh-dashboard` run and the read-only
post-run checks.  It records observations only; a successful refresh does not
mean that every optional provider or delivery boundary is healthy.

## Follow-up observation — 2026-08-21

The subsequent `refresh-dashboard` dispatch (`32399919833`) also completed
successfully and published a `ready` manifest (`release-bc85f95f9fd88245`).
The latest Railway health read remains fail-closed: Jin10 and the monitor are
healthy, while Gmail is `configuration_missing`, GDELT is `HTTP_429`, and the
health callback is `HTTP_403`.  Delivery evidence is still the earlier scoped
photo smoke receipt, not a new FinancialJuice/Creator production receipt.
Therefore this observation does not change the acceptance state below.

## Refresh-dashboard

- Workflow: [32340655743](https://github.com/hanjhou2000716/prstklab-stk-detector/actions/runs/32340655743)
- Event: `workflow_dispatch`
- Ref: `main` (`87a15e1b19626732726e7d73fb6cdc02f8f79cfc`)
- Observed conclusion: `success`
- Scope: market/research/event refresh and Pages release publication.

## Public release manifest

The cache-busted public manifest returned HTTP 200 after the workflow:

| Field | Observed value |
|---|---|
| `release_id` | `release-b8983a5784eed894` |
| `created_at` | `2026-08-20T06:42:52.177163+00:00` |
| `status` | `ready` |
| market snapshot | `f2211deb6cd69070` |
| research snapshot | `research-8b8ec8f6e5ee51aa` |
| event snapshot | `event-ed531dee05c7de49` |
| creator release | `creator-68322d49d4596ba0` |
| creator status | `ready` |
| news status | `ready` |
| validation errors | `[]` |

The manifest is a lineage and availability check.  It does not claim that
the research snapshot is fresh; the manifest still reports
`research_freshness=stale_fallback`.

## Railway health observed after refresh

The public health endpoint returned HTTP 200 and `status=ok`.  The monitor was
running with a healthy heartbeat and Jin10 was healthy at the observation
time.  The following independent conditions remain open:

- GDELT was `failed` with a runtime error and its health callback was
  `permission_denied`/HTTP 403.  No stale cache was used.
- Market sync and delivery were `not_checked`; this run did not constitute a
  Telegram delivery acceptance test.
- Gmail ingress remained `configuration_missing`.
- Railway runtime configuration still reported the legacy delivery-secret
  name as active and `migration_required=true`; no secret value is recorded.

These conditions must remain visible in source health and must not be
interpreted as "no event" or as evidence that a high-risk alert is safe to
send.

## Gate interpretation

This evidence closes only the approved dashboard refresh/public manifest
check.  It does **not** close Railway restart continuity, canonical secret
migration, Gmail/Creator/FinancialJuice live ingress, GDELT availability, or
single-recipient Telegram delivery.  Those remain explicit follow-up debts
and the release gate remains fail-closed for stale, unverified, or renderer
failed data.
