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

The card is temporary runtime output and is not written to `data-release`; the
snapshot and manifest remain the source of truth for Mini App rendering.

## Public card file-id reuse

When `TELEGRAM_FILE_ID_CACHE_PATH` (or the `cache_path` argument) points to a
persistent JSON file, the first successful recipient upload stores only the
public card hash, alert/release identifiers, Telegram `file_id`, and creation/
last-use timestamps. Later recipients reuse that Telegram `file_id` instead of
uploading the same card again. Recipient IDs and message payloads are never
stored. A missing or unreadable cache is safe: the first recipient uploads the
card and the remaining recipients still receive independent messages.
