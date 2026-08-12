# P0 Gmail Intelligence Gateway

The Railway monitor now has a bounded, fail-closed Gmail ingestion boundary:

`Gmail Watch → authenticated Pub/Sub push → ingress → parser/router → private SQLite state`

## Safety contract

- `GMAIL_WATCH_TOPIC`, a dedicated `GMAIL_WATCH_LABEL_IDS`, OAuth state, Pub/Sub
  audience and expected service account are required before the watch reports
  `configured`.
- Pushes require a bearer identity and exact audience/service-account matches.
  Invalid or oversized requests are rejected before parsing.
- Only sanitized observation metadata and hashes are stored. Raw body text and
  attachments are never written to the store, public artifacts, Pages or logs.
- Known sources with an unknown template are `unsupported_template`; unknown
  senders are `invalid_source`. Both enter the DLQ and cannot create an event or
  Telegram alert.
- Gmail message IDs and content hashes are unique, so Pub/Sub retries and
  Railway restarts are idempotent.

## Configuration

Set these variables in Railway (values are not committed):

```text
GMAIL_WATCH_TOPIC=projects/<project>/topics/<topic>
GMAIL_WATCH_LABEL_IDS=Label_123
GMAIL_OAUTH_STATE=configured
GMAIL_PUBSUB_AUDIENCE=https://<railway-host>/gmail/push
GMAIL_PUBSUB_SERVICE_ACCOUNT=<verified-pubsub-service-account>
```

Until all values are present, source health is `configuration_missing`, not
`healthy`. The actual Gmail API watch renewal and JWT cryptographic verification
remain deployment adapters; this contract requires their verified identity to be
passed to the ingress and never accepts an unverified push.

## Rollback

Disable the Gmail watch subscription and remove the new Railway route. Existing
Jin10/GDELT and public release paths are independent. The private SQLite file can
be retained for replay or removed after the retention policy is reviewed.
