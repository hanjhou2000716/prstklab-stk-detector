# Telegram photo delivery

`scheduled_delivery --send-only` now renders the fixed card only after the
public release gate passes, then calls `send_photo_briefs`. Each recipient gets
one `sendPhoto` message containing a caption of at most 40 characters, the
fixed card, and an inline Mini App deep link targeting the same alert/release.

`send_photo_briefs` isolates recipients and returns one receipt per chat. A
blocked chat, a bounded 429 retry, or a transport failure is recorded without
stopping delivery to the remaining recipients. Receipts contain only a
recipient hash plus alert/release/snapshot IDs. Tests mock Telegram and must
never use production chat IDs.

Photo captions apply the same public display policy as text notifications:
colour cues may remain, while internal R0–R4 risk codes are removed before the
Telegram request is built. The original risk grade remains available in the
delivery and release audit records.

The card is temporary runtime output and is not written to `data-release`; the
snapshot and manifest remain the source of truth for Mini App rendering.
