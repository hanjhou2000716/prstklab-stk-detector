# Telegram production notification policy

Production scheduled and event notifications use one `sendPhoto` message after
the release gate succeeds. The message contains a short caption (maximum 40
Unicode characters), a validated 1080x1350 PNG, and a Mini App inline button
whose query includes the alert, release, and snapshot identifiers. Full
evidence, provenance, market context and research details remain in the
release referenced by the button.

The renderer is fail-closed: a missing browser, invalid dimensions, blank
image, or missing required fields blocks delivery and records the renderer
error type. It never sends a solid or blank fallback card. The scoped photo
smoke test still requires one explicit test chat ID and must never use the
normal broadcast list.

## Rollback

Revert the production transport commit and re-run the release gate. The photo
smoke test is independent and can remain available for renderer diagnostics.
