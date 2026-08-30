# Telegram production notification policy

> Current policy: scheduled, official-event, emergency, research, system-health
> and FinancialJuice production use one release-gated text message. The only
> photo exception is a verified Creator email attachment.

Production scheduled and event notifications use one `sendMessage` after the
release gate succeeds. The canonical R0–R4 risk grade is included in the
bounded text; full evidence, provenance, market context and research details
remain in the release referenced by the Mini App deep link. A verified Creator
attachment may use one `sendPhoto` with the same release lineage.

The renderer is fail-closed: a missing browser, invalid dimensions, blank
image, or missing required fields blocks delivery and records the renderer
error type. It never sends a solid or blank fallback card. The scoped legacy
photo-smoke input now runs text-only acceptance, requires one explicit test
chat ID, and must never use the normal broadcast list.

## Rollback

Revert the production transport commit and re-run the release gate. The photo
smoke test is independent and can remain available for renderer diagnostics.
