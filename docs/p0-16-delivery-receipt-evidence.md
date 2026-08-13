# P0-16 Telegram delivery receipt contract

Delivery metadata is bound to the release, snapshot, alert and trace that
produced it. Receipts persist only a truncated recipient hash; raw Telegram
chat IDs and bot secrets are excluded. Per-recipient outcomes remain isolated,
so a retryable or blocked recipient cannot overwrite another recipient's
successful delivery.

The Railway callback payload carries counts, status and lineage fields and is
safe to retry without exposing message content. Production delivery remains
behind the release gate; these tests are transport-free contracts.
