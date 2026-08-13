# P0-17 Creator photo delivery contract

Creator notifications use a transport-neutral plan before Telegram is called.
The plan is release-gated, idempotent by `creator_episode_key` plus
`notification_type`, and carries a release-bound Mini App deep link.

When the private summary image is available the transport may use
`sendPhoto`. If it is unavailable, the plan explicitly degrades to one
text-only notification (`media_degraded`) instead of sending a black or empty
image. The receipt stores only a recipient hash and safe lineage fields:
episode, creator snapshot, release, message ID, media mode/hash and status.

This module does not call Telegram and therefore is safe for offline tests.
The existing recipient-isolated retry policy in `src/telegram_client.py` is
responsible for transport retries and delivery receipts.

Rollback: revert the feature commit. Existing emergency/photo delivery remains
unchanged.
