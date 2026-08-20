# FinancialJuice delivery trace contract

Qualifying FinancialJuice items (`vendor_importance >= 8`) remain separate from
PRStK risk.  The scheduled delivery path now carries an allow-listed trace from
the release-bound event into the Railway delivery receipt:

`received_at` → `parser_version` → `observation_id_hash` → `item_id` →
`event_cluster_key` → `vendor_importance` → `prstk_risk` →
`notification_reason` → `release_id` → `snapshot_id` → `delivery_status`

Only the hashed observation identity is sent to Railway.  Raw Gmail/message IDs
and transport fields are never exported.  The callback rejects a trace whose
release or snapshot does not match the receipt envelope, so a successful
delivery cannot be attributed to a different public release.

The trace is retained inside the Railway outbox payload and is available to
delivery-health diagnostics.  A missing or malformed trace fails the callback
before persistence; it does not silently create an incomplete receipt.

## Verification

- `tests/test_delivery_callback.py` validates allow-listing, hash shape and
  release binding.
- `tests/test_railway_delivery_store.py` validates durable receipt retention
  without raw identity leakage.
- The scheduled workflow serializes structured outputs as compact JSON before
  passing them to the callback.

## Rollback

Revert the atomic commit that introduces this contract.  Existing generic
delivery receipts remain readable; no market or research artifact is changed.
