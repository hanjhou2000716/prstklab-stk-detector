# Production Telegram photo delivery

Scheduled, official-event and emergency notifications use one release-gated
`sendPhoto` call per recipient. The message contains an at-most-40-character
caption above a validated 1080×1350 PNG and an inline Mini App button targeting
the same alert, release and snapshot. A renderer or font failure blocks the
send; no black or single-colour fallback is transmitted.

The first successful recipient uploads the card. Subsequent recipients reuse
the returned Telegram `file_id`, while each recipient receives an independent
delivery receipt. Only a short hash of the file ID and chat ID may be persisted.
Transient failures are bounded and a blocked recipient does not stop other
recipients.

## Rollback

If the renderer or Telegram path is unhealthy, keep the last successful release
public, stop notification at the release gate, and rerun the scoped photo smoke
workflow with one explicit test chat ID. Revert the transport commit only after
the current release and delivery receipts are archived.
