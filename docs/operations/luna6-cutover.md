# luna6 PRStK incident-mail cutover (no custom domain)

This runbook describes the implementation and the remaining owner-operated cutover. Nothing in this repository deploys the Worker, creates Google credentials, edits the external schedules, or sends a production message automatically.

The legacy GitHub outlet no longer manufactures a failed Actions run to imitate an email. It records a due decision as `not_sent` and leaves delivery to the coordinator. Therefore, once these workflow changes are merged, ordinary incident email is unavailable until the owner completes the Worker live cutover. Keep the merge and external cutover coordinated; do not mistake a successful legacy outlet run for delivery.

## Architecture and free-tier boundary

- The incident API is a private Cloudflare Worker exposed at its native `https://<worker>.<account>.workers.dev` origin. It does not require a domain, DNS zone, custom route, or certificate setup.
- Durable state uses one SQLite-backed Durable Object for the repository. Cloudflare's published Free-tier baseline currently includes 100,000 Workers requests/day, 10 ms CPU time per Worker invocation, 100,000 Durable Object requests/day, 13,000 GB-s/day, 5 million SQLite rows read/day, 100,000 rows written/day, and 5 GB total SQLite storage. These ceilings are separate; measure the actual account's existing usage before cutover because other Workers can consume the account-wide request allowance. Recheck live limits because quotas can change; do not enable paid overages or upgrade automatically. When a Free limit is reached, operations fail visibly and the Telegram watchdog must report the degraded state rather than creating paid capacity.
- A separate Google Apps Script project polls the public, minimal Worker liveness endpoint and GitHub's public workflow API every five minutes. It sends a private Telegram message only on state transitions. This is the free independent monitor; it does not depend on Supabase or a custom domain.
- The Worker owns the single incident/outbox state. GitHub Issues remain a readable view. A one-time manual, read-only importer preserves the #1143 journal and relevant incident history as a notification-suppressed, content-hashed snapshot.
- Gmail sending uses a dedicated free sender account. Receipt verification uses the existing recipient mailbox `hanjhou2000716@gmail.com` with a separate read-only OAuth grant. Sender credentials and market-data credentials remain separate.

The implementation targets the Free tier, but the service owner must re-check the current provider quotas and account plan before deployment. It never provisions paid capacity.

## Required owner setup

### 1. Dedicated Gmail sender and OAuth

1. Create a Gmail account used only for PRStK incident mail. Do not reuse market-data OAuth credentials.
2. In a Google Cloud project owned by the account owner, enable Gmail API and create an OAuth Desktop client.
3. Configure the consent screen for the owner's intended personal use. Do not leave the app in **Testing**: Google may expire refresh tokens issued to a Testing app after seven days. Personal-use / under-100-user exceptions may apply, but Google can still revoke a token; the Worker health check verifies both token refresh and account identity continuously.
4. Authorize the sender account with `gmail.compose` and `gmail.readonly`. Separately authorize `hanjhou2000716@gmail.com` with `gmail.readonly` only. Never paste passwords, authorization codes, access tokens, refresh tokens, or client secrets into chat or the repository.
5. Confirm both OAuth profiles return the expected account identity before cutover. From the trusted `main` workflow, manually dispatch `Owner-triggered incident mail verification` with `confirm_send=yes` and a unique 16–64 character verification ID. The endpoint has no arbitrary body or recipient fields and fixes the recipient to `hanjhou2000716@gmail.com`. Reuse the same ID after an ambiguous workflow response; a new ID creates a new test decision. Wait for the receipt checker and verify the exact Message-ID in the recipient inbox. `sent_verified` alone is not inbox proof. This message does not count as a natural market notification.

### 2. Worker deployment and secrets

The repository's Worker is configured to use SQLite Durable Objects and `workers.dev`. The owner deploys only after code review and the Worker tests pass. Do not enable `INCIDENT_OPS_MODE=live` until the shadow health report says the sender, recipient verification, Telegram fallback, storage, and backlog are ready.

Set the Worker variable `INCIDENT_OPS_MODE=shadow` first and the exact repository identity `INCIDENT_REPOSITORY=hanjhou2000716/prstklab-stk-detector`, `INCIDENT_REPOSITORY_ID=1309835643`, and audience `https://prstk-incident-ops`. Set the GitHub Actions repository variable `INCIDENT_OPS_MODE=shadow` as well. These are separate controls: evidence ingestion rejects a mode mismatch, and the five-minute health workflow fails on a mismatch. Set the GitHub repository variable `INCIDENT_OPS_URL` to the exact `workers.dev` origin.

Set the following as Worker Secrets, never as committed variables:

- `INCIDENT_GMAIL_OAUTH_CLIENT_ID`
- `INCIDENT_GMAIL_OAUTH_CLIENT_SECRET`
- `INCIDENT_GMAIL_REFRESH_TOKEN`
- `INCIDENT_GMAIL_FROM` (the dedicated sender address)
- `INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_ID`
- `INCIDENT_RECEIPT_GMAIL_OAUTH_CLIENT_SECRET`
- `INCIDENT_RECEIPT_GMAIL_REFRESH_TOKEN`
- `INCIDENT_RECEIPT_GMAIL_ADDRESS=hanjhou2000716@gmail.com`
- `INCIDENT_TELEGRAM_BOT_TOKEN` (a dedicated bot used only for private administrator fallback)
- `INCIDENT_TELEGRAM_ADMIN_CHAT_ID` (the administrator's private chat)

The existing Worker `ADMIN_KEY` secret protects the owner-only `GET /ops/outbox/state` endpoint. Keep its current value and use it only from a private administrative client; do not place it in GitHub variables, Apps Script, or workflow artifacts. Routine workflows use GitHub OIDC instead.

Use the provider's secret-entry flow from the owner's own terminal or dashboard. Do not put secret values in shell history, workflow artifacts, issue bodies, or logs. Verify `GET /ops/health` using the trusted heartbeat workflow; do not expose the admin outbox endpoint publicly.

The resulting origin is `https://<worker>.<account>.workers.dev`. The independent monitor calls only `/public/ops/liveness`, which exposes the component name and observation time; the administrative health, outbox, and recipient data remain OIDC-protected.

### 3. Independent Telegram watchdog

1. Open `ops/google-apps-script/Code.gs` in a private Apps Script project owned by the administrator. Share the project with no one else.
2. Add Script Properties:
   - `PRSTK_WATCHDOG_WORKER_BASE` = the exact `workers.dev` origin, without a path.
   - `PRSTK_WATCHDOG_TELEGRAM_BOT_TOKEN` = a dedicated Telegram bot token.
   - `PRSTK_WATCHDOG_TELEGRAM_CHAT_ID` = the owner's private administrator chat ID.
3. Run `setupPrstkWatchdog()` once and approve Apps Script's external-request and trigger permissions. It removes duplicate triggers for this handler and creates one five-minute trigger.
4. Run `pollPrstkWatchdog()` manually once to authorize and confirm the initial state. Then run `sendPrstkWatchdogTelegramTest()` manually once and confirm the labelled message arrives in the private administrator chat. The script will not send a healthy startup message. A later state change sends one message; an ambiguous Telegram response is recorded and never blindly retried for the same transition.
5. Confirm the Worker liveness timestamp is no more than five minutes old and the latest successful GitHub heartbeat is no more than twenty minutes old. Future-dated evidence is classified as ambiguous; the monitor does not subtract an hour or infer a successful time.

Apps Script and Telegram still have provider quotas and can be revoked or unavailable. Keep their failure visible in the Apps Script execution history and check the bot's private chat during acceptance.

## One-time history import

After the Worker is deployed in shadow mode and its identity/health checks pass, dispatch **Import legacy incident state** from `main` with `confirm_import=true` exactly once. The workflow has read-only GitHub permissions plus OIDC; it cannot edit or close issues. It verifies the #1143 marker and journal schema, imports only confirmed half-hour decisions with the fixed recipient hash, and stores an immutable snapshot under a deterministic journal-generation/hash ID. Notifications are suppressed during import.

The importer fetches the exact #1145 recovery evidence afresh. It marks #1145 recovered only if the two distinct central runs and the matching recovery-health run have the exact workflow path, repository, `main` branch, full baseline SHA, attempt, completed-success terminal state, bound artifact identity/digest, complete result, and matching recovered issue number. If any proof is unavailable, it imports #1145 as `historical_pending_verification`; a closed issue alone never proves recovery. #1120's four missed morning slots remain `historical_diagnosed`, and #1099 remains pending verification. #1144 has a separate verified recovery on the baseline main SHA: central reconciliation run `41323876507` records the official monitor liveness audit as healthy and `audit_incident_recovered=[1144]`, with complete coverage, accepted handoff, and no unprocessed sources. Import that lifecycle as recovered only after the importer independently rechecks the run, attempt, SHA, artifacts, and result; #1145 or any later healthy status cannot substitute for it.

If the workflow response is ambiguous, inspect the immutable import artifact and the coordinator migration status before dispatching again. Replaying the same journal generation/hash resumes the first stored snapshot and does not notify or replace its evidence.

## Cutover order

1. Review the merged code and confirm the exact main SHA. Confirm no old producer/consumer run remains active before disabling the legacy outlet.
2. Deploy the Worker in shadow mode with the SQLite Durable Object. Confirm the specific `workers.dev` public liveness response, OIDC identities, and private health response.
3. Run the one-time import and verify the saved snapshot, imported confirmed-window count, migration status `completed`, and all incident lifecycles. The importer must not create a draft or message.
4. Use the trusted owner verification workflow to send one explicitly labelled message and test Gmail sender profile, fixed Message-ID, real inbox visibility, and the separate recipient OAuth. Run the Apps Script Telegram test function once and confirm the private administrator chat. These tests are excluded from natural acceptance.
5. Observe shadow decisions across the normal half-hour boundaries. Check that one fixed window and recipient create one decision regardless of consumer workflow reruns.
6. After explicit owner review, switch both mode controls at a quiet boundary after all old outlet runs have drained. Set the Cloudflare Worker variable `INCIDENT_OPS_MODE=live` first while the GitHub Actions repository variable remains `shadow`; then immediately set the GitHub variable to `live`. During this brief mismatch, evidence handoff fails closed and normal mail delivery is not available; the independent five-minute Telegram watchdog reports a failing or stale GitHub heartbeat. Confirm both controls agree on `live`, the new sender is healthy, and a real inbox receipt is verified before starting acceptance. Do not reverse the order: setting GitHub to `live` while the Worker is still `shadow` disables the unified sender before it can deliver.
7. Update the existing external schedules without changing their IDs:
   - Morning job `8137460`: daily at 06:00, `Asia/Taipei`.
   - U.S. premarket job `8146101`: weekdays at 09:00, `America/New_York`; send payload version `v4`; the receiver independently confirms whether the U.S. market is open.
8. Verify the exact Pages deployment binding, build/release identity, public manifest and content hashes. Record the Worker live switch, each schedule's actual effective time, and exact public Pages version.
9. Define `T` only after all code, service, Pages and external schedule changes are effective. A behavior-changing repair resets `T`.

Do not batch-delete or auto-archive old GitHub mail. After the new Gmail path is verified, create a user-owned Gmail rule that matches only this repository's trusted GitHub sender plus the exact PRStK CI notification identity, adds a dedicated label, and skips the inbox while keeping the original message and unread state. Test the rule against a new matching message and at least one unrelated GitHub project message before enabling it. Do not retroactively apply it.

## Seven-day natural acceptance

The minimum observation is seven consecutive days from `T`, including weekdays and a weekend, with at least the final twenty-four hours stable. Preserve each run's full SHA, attempt, artifact and digest, source slot/anchor/deadline, exact public release and deep links, recipient roster, per-recipient durable receipt, notification decision and Gmail receipt.

Required samples:

- Two consecutive naturally scheduled morning reports, including a weekend morning.
- Two applicable Taiwan premarket runs, two Taiwan postmarket runs, and two U.S. premarket runs.
- FJ at least 9/10, price events, and official emergency events only when they naturally qualify; preserve each original deadline. No candidate, no-op, expired-not-attempted, or historical fallback does not count as a delivery.
- Every normal email mapped to one durable decision and one verified inbox receipt. Each fixed half-hour window may produce at most one consolidated reminder to the fixed recipient. Historical replays must not send; critical alerts require a new verified impact in the same generation.
- Each recovery names its own incident and two distinct, complete evidence runs. A healthy workflow, a closed issue, an empty inbox search, or another incident's recovery is not a recovery proof.

The seven-day timer is a minimum, not an automatic declaration of completion. If an event-based sample does not occur naturally, record it as still pending and continue observing. Do not replay production market mail.

## Rollback and stop conditions

- If Gmail authorization, inbox receipt verification, or notification decisions become uncertain, set the Worker back to shadow mode after owner review; do not blind-resend a `delivery_unknown` decision.
- Keep the decision ledger, snapshots, delivery IDs and historical receipts. Do not clear dedupe or migration state.
- Keep independent Apps Script/Telegram monitoring active. Preserve original evidence and the actual failed workflow result.
- Do not restore the deliberate native failure as a live alert channel, batch-send missed reports, edit history to claim delivery, or automatically enable paid capacity.
- If a code or behavior-setting change is made during natural acceptance, record a new `T` after every affected component is effective.

## Relevant provider references

- [Cloudflare workers.dev routing](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/) — native hostname; no custom domain required.
- [Cloudflare Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) — check current account eligibility and quotas before deployment.
- [Google OAuth personal-use exception](https://support.google.com/cloud/answer/13464323?hl=en) and [refresh token expiration](https://developers.google.com/identity/protocols/oauth2#expiration) — do not use Testing status for a long-running integration.
- [Apps Script time triggers](https://developers.google.com/apps-script/reference/script/clock-trigger-builder) and [quotas](https://developers.google.com/apps-script/guides/services/quotas) — independent five-minute watchdog limits.
