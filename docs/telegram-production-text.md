# Production Telegram delivery

Scheduled and official production notifications use one `sendMessage` call
after the release gate succeeds. The message contains the existing 30-character
caption and the Mini App inline button; the button points at the same release
and alert context. Full evidence remains in the immutable release.

The 1080×1350 renderer is intentionally development/smoke-test only. The
`photo_test` workflow requires one explicit test chat ID and is the only path
that installs Chromium and calls `sendPhoto`. A renderer or font failure can
therefore never block scheduled market delivery, and no black fallback image
is sent.

## Rollback

Revert the production transport commit and rerun the release gate. Keep the
scoped photo smoke workflow independent for renderer diagnostics.
