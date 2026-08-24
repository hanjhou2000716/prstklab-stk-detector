# Gmail Watch IAM runbook

This runbook records the least-privilege boundary for the Gmail Watch used by
PRStK. It does not contain OAuth tokens, refresh tokens, mailbox IDs,
service-account keys or Pub/Sub secrets.

## Required resources

1. A Google Cloud project with the Gmail API and Pub/Sub API enabled.
2. One Pub/Sub topic for Gmail push notifications.
3. One push subscription with bounded acknowledgement and retention policies.
4. A Gmail OAuth grant for the monitored mailbox with the minimum scope needed
   by the Watch/history reader.

## IAM boundary

- The service account used by Gmail push delivery needs permission to publish
  to the single topic only (`pubsub.topics.publish` on that topic).
- The Railway runtime identity that consumes the subscription needs subscriber
  permission on that subscription only (`pubsub.subscriptions.consume` and
  `pubsub.subscriptions.get`).
- An operator may retain project-level administration for setup, but the
  runtime must not rely on a broad Editor role for normal operation.
- No service-account key should be created for Railway when workload identity
  or a managed runtime identity is available.

## Safe verification

Verify these facts in Cloud Console or with an authenticated read-only command:

- topic exists and is in the intended project;
- subscription exists, is a push subscription and points to the intended
  Railway ingress URL;
- Gmail Watch expiration is visible only as a timestamp in `/health`;
- the history cursor is present only as a redacted hash;
- no message body, mailbox address, token or key appears in logs or health.

## Rotation and recovery

- Renew the Watch before expiration; a failed renewal is `watch_status=failed`
  or `configuration_missing`, never `healthy`.
- Rotate OAuth credentials through the provider console and Railway variable
  manager; do not commit or paste values into GitHub issues, PRs or logs.
- If the subscription is recreated, run a history sync from the durable cursor
  before treating the ingress as healthy.
- Keep the release gate fail-closed until a sanitized observation and delivery
  receipt are traceable to one release.

## Current audit result

The read-only 2026-08-24 audit found the Pub/Sub topic and subscription and a
healthy Gmail Watch lease. It did not change IAM, create a key, read a secret,
or send a message. A live sanitized event remains an external acceptance gate.

The companion [IAM audit](google-cloud-gmail-iam-audit-20260824.md) records the
observed push settings and the project-level `calendar-reader` Editor finding.
Permission reduction remains a separately confirmed change; it must not be
papered over by creating a service-account key.
