# Railway external acceptance runbook

This runbook closes the operator-managed part of the external acceptance gate
without exposing any credential values. It is intentionally separate from
the read-only evidence capture and does not weaken the release gate.

## 1. Gmail Creator／FinancialJuice ingress

In the Railway production service, configure these variables with the values
from the Google Cloud Pub/Sub and Gmail OAuth setup:

- `GMAIL_WATCH_TOPIC`
- `GMAIL_WATCH_LABEL_IDS`
- `GMAIL_OAUTH_STATE`
- `GMAIL_PUBSUB_AUDIENCE`
- `GMAIL_PUBSUB_SERVICE_ACCOUNT`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `GMAIL_STATE_PATH` (a persistent volume path, normally `/data/gmail-ingress.sqlite3`)

After the service restarts, `/health` must report `gmail.status=healthy` or
`watch_status=active`. The monitor renews the watch automatically when its
lease is near expiry. `configuration_missing` is not equivalent to
`no_new_content` and must remain visible until the watch is actually active;
`watch_status=failed` records a provider/configuration failure without
stopping the other polling loops.

## 2. Delivery callback secret migration

Create the canonical Railway variable `RAILWAY_STATUS_SHARED_SECRET` with the
same secret value currently used by the delivery callback. Keep the legacy
`DELIVERY_STATUS_SHARED_SECRET` only during the migration window; once the
canonical variable is confirmed active, remove the legacy variable and restart
the service. Never place either value in Git, logs, artifacts, or Telegram.

Acceptance evidence must show:

- `canonical_name_present=true`
- `migration_required=false`
- callback status `healthy`

## 3. GDELT recovery

Do not bypass GDELT rate limits. A `429` must remain fail-closed while the
bounded exponential backoff and at-most-two-hour stale-cache policy run. Wait
for a successful poll or an explicitly valid stale-cache observation, then
capture a new redacted external-acceptance report. The health callback `403`
is a separate GitHub dispatch permission issue and must not be reported as a
successful GDELT scan.

## 4. Verification order

1. Restart the Railway service after configuration changes.
2. Capture `/health` and the public Pages manifest with:

   `uv run python -m src.external_acceptance --railway-url <public-health-url> --public-url <pages-url> --output external-acceptance.json`

3. Require `status=PASS` before running the release-gated, single-recipient
   photo workflow.
4. Confirm the receipt's release/snapshot/observation lineage and the Mini App
   deep link before considering production acceptance complete.

If any step fails, keep the previous ready release and do not send a Telegram
message. The safe rollback is to restore the prior known-good Railway
variables and redeploy the previous release; no public artifact is deleted.
