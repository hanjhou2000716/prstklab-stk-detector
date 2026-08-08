# Telegram photo delivery

`send_photo_brief` sends one `sendPhoto` message: a caption of at most 40
characters, a fixed card, and an inline Mini App deep link. The returned
receipt contains only a recipient hash plus alert/release/snapshot IDs. Tests
mock Telegram and must never use production chat IDs.
