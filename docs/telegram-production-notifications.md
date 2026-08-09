# Telegram production notification policy

> Current policy: scheduled production uses `sendMessage` text delivery. The
> legacy photo description below applies only to the scoped `photo_test`
> diagnostic workflow; see `docs/telegram-production-text.md`.

Production scheduled and event notifications use one `sendMessage` after the
release gate succeeds. The message contains the existing short caption (at
most 30 characters) and a Mini App inline button whose query includes the
alert, release, snapshot and view identifiers. Full evidence, provenance,
market context and research details remain in the release referenced by the
button. The fixed 1080x1350 image is reserved for the explicit single-recipient
`photo_test` smoke workflow.

The renderer is fail-closed: a missing browser, invalid dimensions, blank
image, or missing required fields blocks delivery and records the renderer
error type. It never sends a solid or blank fallback card. The scoped photo
smoke test still requires one explicit test chat ID and must never use the
normal broadcast list.

## Rollback

Revert the production transport commit and re-run the release gate. The photo
smoke test is independent and can remain available for renderer diagnostics.
