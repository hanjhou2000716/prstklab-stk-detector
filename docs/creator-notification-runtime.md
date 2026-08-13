# Creator notification runtime

Creator episodes are release-bound and idempotent.  The notification boundary
checks the parent release before touching Telegram, then uses the stable
`creator:<episode_key>:<notification_type>` key to prevent duplicate sends
after Gmail/Pub/Sub retries or a Railway restart.

When an approved private media path is available, the runtime uses the shared
`sendPhoto` contract and a Creator deep link.  If media is missing or every
photo attempt fails, it sends one bounded 30-character text notification with
the same deep link and records `media_mode=text_only`; it never sends a blank
or synthetic image.  Each recipient receives an independent, privacy-safe
receipt containing only a recipient hash and release/snapshot lineage.

The runtime is transport-injectable for offline tests.  Production callers
must pass a `status=ready` release result and a private media path obtained
from the Railway media boundary; public Pages artifacts never contain media
URLs or raw email content.

Rollback: disable the Creator notification feature flag or stop invoking
`deliver_creator_episode`.  Market, event and research delivery remain
unchanged.

## Scheduled workflow boundary

The scheduled market workflow invokes `src.creator_dispatch` only after the
same public Pages release gate used by the core market brief returns
`allowed=true`.  Creator delivery is disabled unless the repository variable
`CREATOR_NOTIFICATION_ENABLED` is explicitly set to `true`; an absent or
false value is a safe no-op.  Configure `CREATOR_RECORDS_PATH` only with a
sanitized, structured records file outside `site/`, and keep `CREATOR_MEDIA_ROOT`
on a private runner path.  Raw Gmail messages, attachments, tokens and chat
IDs must never be copied into the public release.

The workflow sends the bounded Creator receipt to Railway with
`receipt_kind=creator` after dispatch.  The receipt contains release,
snapshot, alert, delivery mode and aggregate counts, but no raw recipient
identifier.  A Railway callback failure is observable and retryable and does
not invalidate the already-published release.  To roll back a bad Creator
release, first set `CREATOR_NOTIFICATION_ENABLED=false`; the parent market
release and prior ready Creator artifact remain available.

### Verification checklist

1. Confirm the manifest and Creator artifact are both `status=ready` and hash
   verified before enabling the variable.
2. Use a single non-production test recipient and a sanitized private media
   fixture for the first run.
3. Confirm the Telegram deep link contains the Creator release and episode
   key, then inspect the Railway delivery receipt for the same release and
   snapshot IDs.
4. If media rendering fails, expect a bounded text-only delivery with
   `media_mode=text_only`, never a blank image.
