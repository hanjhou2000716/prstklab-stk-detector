# Telegram production notification policy

Production scheduled and event notifications use `sendMessage` only. The
message is a short (maximum 30 characters for the existing brief contract)
summary plus the Mini App inline button. Full evidence, provenance, market
context and research details remain in the release referenced by the button.

The Playwright renderer and `sendPhoto` client remain available only for the
explicitly scoped photo smoke test. A smoke test must provide one test chat ID;
it must never use the normal broadcast list.

## Rollback

Revert the production transport commit and re-run the release gate. The photo
smoke test is independent and can remain available for renderer diagnostics.
