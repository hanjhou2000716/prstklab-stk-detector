# Production release checklist

This checklist is for maintainers after the stacked PRs have been merged.  It
keeps data freshness, evidence and delivery checks separate so a successful
workflow cannot be mistaken for a successfully delivered alert.

## Before dispatch

- [ ] `release-manifest.json` is `ready` and every artifact hash verifies.
- [ ] Market and research snapshots have distinct IDs and valid freshness.
- [ ] `runtime_audit` and schema/invariant validation pass.
- [ ] Stale, delayed or unverified quotes are excluded from alert decisions.
- [ ] Research state distinguishes `no_candidates`, `building`, `data_unavailable`
      and `failed`.
- [ ] Telegram uses only plural `TELEGRAM_CHAT_IDS`; no singular fallback is set.

## Delivery gate

- [ ] Pages is publicly readable and returns the expected `release_id`.
- [ ] Card renderer produced a readable PNG exactly 1080×1350 pixels.
- [ ] Caption is at most 40 Unicode characters and contains no secret or raw
      recipient ID.
- [ ] One `sendPhoto` message contains the caption, photo and deep-link button.
- [ ] Each recipient has an isolated receipt (`delivered`, `partial`, `failed`
      or `blocked`).
- [ ] Railway `/health` shows the same release, alert and delivery trace.

## Post-dispatch audit

- [ ] Mini App query parameters open the matching `alert`, `release` and `view`.
- [ ] Event timeline shows lifecycle transitions and any suppression reason.
- [ ] Source health separates `no_events` from `scan_failed`.
- [ ] No event was repeated solely because the poller ran again.
- [ ] Keep the release and receipt artifacts for the retention period.

## Safe failure behavior

If any item fails, do not infer that the market is safe and do not send a
high-risk alert.  Mark the release degraded, preserve the failed evidence, and
retry only the failed stage.  If Pages or manifest verification fails, restore
the last successful release before re-enabling notification.
