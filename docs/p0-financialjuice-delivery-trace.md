# P0-12 FinancialJuice delivery trace

FinancialJuice remains a discovery source. Its vendor importance (8/10 or
above) can make an item notification-eligible, but it is never substituted for
the PRStK risk level and never bypasses the release gate.

Each reviewed item now carries the following public-safe trace fields:

- `received_at`: ingress time (falling back to fetched/published time only when
  the reviewed record does not provide ingress time).
- `parser_version`: parser version from ingress, or the shared external-event
  pipeline version.
- `observation_id_hash`: SHA-256 of the reviewed observation key; the raw
  transport/Gmail identifiers are not admitted at the privacy boundary.
- `item_id` and `event_cluster_key`: stable item and cross-source identities.
- `vendor_importance` and `prstk_risk`: separate vendor and platform risk
  dimensions.
- `notification_reason`: explicit eligibility, deduplication, or pending
  confirmation reason.

After a release passes the gate and the photo delivery completes, the private
delivery output and durable event ledger add `release_id`, `snapshot_id`, and
`delivery_status`. This makes the Gmail → parser → event → release → Telegram
path auditable without publishing private message IDs or raw content.

Missing evidence remains fail-closed: the item can stay visible as pending or
observe-only, but it cannot become a high-risk alert merely because the vendor
score is high.

## Rollback

Revert the trace commit. Existing event records remain readable because all new
fields are optional for legacy events; no release data migration is required.
