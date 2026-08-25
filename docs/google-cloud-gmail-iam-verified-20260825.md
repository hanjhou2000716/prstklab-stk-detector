# Google Cloud Gmail Watch IAM verification — 2026-08-25

This is a read-only verification of the production Gmail Pub/Sub boundary. It
does not contain OAuth tokens, refresh tokens, service-account keys, mailbox
addresses, message bodies, or secret values.

## Result

The Pub/Sub topic `prstk-gmail-watch` and push subscription
`prstk-gmail-push-sub` are present in the configured Google Cloud project. The
topic permission panel shows the Gmail-managed identity
`gmail-api-push@system.gserviceaccount.com` with the `Pub/Sub Publisher` role.
This is the identity required by the official Gmail push-notification setup;
no additional user-managed publisher account is required.

No IAM policy was changed during this verification. The existing binding is
least-privilege at the topic boundary and is sufficient for Gmail to publish
watch notifications.

## Contract correction

Older repository examples referred to a project-local `prstk-gmail-pubsub`
identity. That name is not the Gmail publisher shown on the production topic.
The audit CLI now defaults to the documented Gmail-managed identity while
still allowing an explicit override for a separately configured integration.

## Remaining acceptance boundary

This verifies IAM configuration only. It does not claim a new mailbox event,
Railway restart-continuity proof, or Telegram delivery. Those remain separate
release-gate evidence requirements and continue to fail closed until observed.

## Rollback

This document and the audit default are non-mutating. Reverting this commit
restores the previous documentation/CLI default; it does not change the
Google Cloud policy or the Gmail Watch lease.
