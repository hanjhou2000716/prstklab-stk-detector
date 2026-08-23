# Gmail Pub/Sub runtime ingress

Railway now exposes a bounded `POST /gmail/push` endpoint alongside the
existing health and delivery endpoints. The handler:

- requires the configured Pub/Sub audience and service-account identity;
- optionally verifies the upstream bearer JWT when
  `GMAIL_PUBSUB_REQUIRE_JWT=true`;
- accepts only the Gmail history cursor (never a message body or attachment);
- persists the cursor in the Railway SQLite state store before returning;
- creates or renews the Gmail `users.watch` lease at startup when the lease is
  missing or within the renewal window;
- returns a generic error without echoing tokens, message IDs, or request data.

The public `/health` response includes a `gmail` component with configuration,
watch, cursor timestamp, and error-class state. `configuration_missing` and
`stale` are operational states; they are not interpreted as “no events”.

Required variables are `GMAIL_WATCH_TOPIC`, `GMAIL_WATCH_LABEL_IDS`,
`GMAIL_OAUTH_STATE`, `GMAIL_PUBSUB_AUDIENCE`,
`GMAIL_PUBSUB_SERVICE_ACCOUNT`, `GMAIL_OAUTH_CLIENT_ID`,
`GMAIL_OAUTH_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`. Set
`GMAIL_STATE_PATH` to a persistent Railway volume path (default
`/data/gmail-ingress.sqlite3`). Raw Gmail content remains
outside this store and is parsed by the bounded source adapters before it can
enter the event or Creator pipelines.

Rollback: remove the ingress route/configuration and redeploy the previous
release. The existing Jin10/GDELT polling and delivery receipt paths are
independent of Gmail ingress.
