# Sanitized external observation ingress

`src/external_observation_input.py` is the only scheduled-pipeline boundary
for FinancialJuice/Gmail-derived observations. It accepts an operator-provided
JSON file referenced by `EXTERNAL_OBSERVATIONS_PATH`; the file must contain
`{"observations": [...]}` (a bare list is also accepted) and every record must
be derived, `public_safe: true`, have a stable `observation_id`, and use the
registered `financialjuice` source.

Raw mail, sender/recipient data, Gmail IDs, attachments, local paths and
private URLs are rejected. Parse failures and duplicate IDs are rejected and
reported through the optional `external_financialjuice` source-health row.
Accepted rows are copied into the prepared market snapshot and therefore flow
through the existing intelligence pipeline, release manifest and release gate;
no record is written directly to `site/data` by this loader.

The path is intentionally opt-in. Until Railway publishes a reviewed
sanitized bundle into the workflow workspace, the source remains
`configuration_missing`/external evidence pending and cannot independently
trigger an alert. This is not a live Gmail bridge and does not expose raw mail.

## Rollback

Unset `EXTERNAL_OBSERVATIONS_PATH` (or revert the ingress commit). The core
market, research and event pipeline continues without external observations;
the existing fail-closed release and notification gates remain unchanged.
