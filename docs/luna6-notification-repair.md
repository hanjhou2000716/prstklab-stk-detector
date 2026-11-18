# LUNA6 notification reliability repair

## Scope and current state

This change keeps GitHub Actions as the Telegram sender and uses the existing
Cloudflare Worker/Supabase receipt path. It covers scheduled market briefs,
eligible realtime alerts, FinancialJuice, Creator text/photo notices, and the
fixed-editor acceptance workflow. Scheduled briefs continue at their existing
slots; a realtime alert remains silent when there is no eligible event.

The supplied GitHub Pages settings screenshot shows **Source: GitHub Actions**
and a live site. That confirms the selected source, not that a new Pages build
was published or that Telegram delivery is working. This change does not alter
cron entries, secrets, OAuth, external schedules, a live Worker, or production
data. The SQL migration is a source artifact only until an account owner applies
it to the intended Supabase project.

## Changes in this repair

1. **Pages package and identity.** Accept the exact zero-byte `site/` parent
   directory produced by the supported archive, while continuing to reject
   traversal, links, duplicate or unsupported members and invalid manifests.
   Use the checked-out source SHA for GitHub's Pages `pages_build_version` and
   retain the full artifact/run/manifest identity separately as
   `release_binding_id`.
2. **Pages diagnostics.** Preserve only a bounded, character-checked
   `X-GitHub-Request-Id` from an HTTP error. Expose it with the distinct
   release-binding ID in the existing workflow evidence so a future natural
   attempt can identify a Pages API rejection without logging credentials or
   arbitrary response headers.
3. **Durable per-recipient Telegram guard.** Before one text or photo API call,
   GitHub Actions obtains an atomic reservation and start from the signed
   Worker endpoint. Supabase stores only hashes of the notification and
   recipient identities, state transitions, Telegram message ID, and bounded
   error category. Message text, bot token, and raw chat ID are excluded.
4. **Replay and retry rules.** A confirmed delivery is not sent again. A
   Telegram `429` can be retried only after its valid `retry_after`, while the
   original delivery deadline and three-attempt limit still allow it. A
   timeout, malformed response, server-side ambiguity, or lost result write
   becomes `delivery_unknown`; it is never automatically resent. A Worker or
   Supabase outage prevents the Telegram call because no durable reservation
   exists. Other recipients continue independently.
5. **Stable identities and deadlines.** Scheduled sends use the original
   slot/date anchor and the existing delivery window; realtime sends use their
   event identity and immutable expiry, or a bounded first-use expiry. A retry
   cannot extend the original deadline. Creator photo and its definite-failure
   text fallback use distinct keys; an ambiguous photo result suppresses the
   fallback to avoid a duplicate message.
6. **OIDC host validation.** Accept the GitHub Actions host apex and its real
   subdomains; reject lookalike suffixes. This does not broaden the remaining
   OIDC claim checks.

## Files and ownership

- Pages package/deployment and workflow evidence: `src/pages_release.py`,
  `src/pages_deployment.py`, `.github/actions/deploy-pages-retry/`, and the
  existing Pages workflows.
- Send guard: `src/telegram_delivery_guard.py` and guarded send methods in
  `src/telegram_client.py`.
- Authenticated Worker route: `worker/src/index.ts`,
  `POST /api/delivery-attempts`.
- Database schema: migration
  `supabase/migrations/202611170001_telegram_delivery_attempt_guard.sql`.
- OIDC and regression coverage: `scripts/incident_ops_auth.py` and the
  relevant tests.

The new endpoint reuses `RECEIPT_CALLBACK_URL` and
`DELIVERY_RECEIPT_SHARED_SECRET`; it does not introduce a new credential. The
existing `/api/delivery-receipt` callback remains the aggregate, per-run
evidence path. The attempt guard is the per-notification/per-recipient send
authority; neither a workflow success nor a queued/no-op decision counts as a
delivered Telegram message.

## Cutover gates

Do these in order. Do not enable guarded scheduled sends until the durable
endpoint is ready, because the sender deliberately fails closed when the guard
is missing.

1. A repository/account owner applies the new migration to the intended
   Supabase project and verifies the two new tables, RLS, service-role grants,
   and RPC signature. Do not import or rewrite existing receipts or dedupe
   history.
2. The owner deploys the Worker code containing `/api/delivery-attempts` with
   the already-authorized shared secret. Verify the route's read-only health or
   an authenticated non-send reserve/start/result contract in a non-production
   test database. Do not call Telegram as part of this check.
3. Read-only account evidence confirms the existing repository variable
   `RECEIPT_CALLBACK_URL` points to the intended Worker receipt endpoint and
   the existing `DELIVERY_RECEIPT_SHARED_SECRET` is available to the relevant
   GitHub Actions send and receipt steps. Do not reveal or rotate the secret.
4. Review and merge this code change only after gates 1–3. The Pages workflow
   remains responsible for the public release. Do not manually rerun a formal
   publication or alter schedule definitions.
5. Observe natural runs. For Pages, require a successful deployment ID,
   artifact digest, source SHA, `pages_build_version`, separate
   `release_binding_id`, deployment identity verification, and public release
   gate all bound to the same run/artifact. For Telegram, reconcile each
   scheduled slot and any eligible alert against the per-recipient state and
   aggregate receipt. A due event with no send attempt remains a failure, not
   a delivery.
6. Start the seven-day natural-delivery observation only after the account
   configuration, Worker, database schema, Pages release path, and original
   schedules are all read-only verified as active. During the window, record
   each original slot/anchor/deadline, published content and canonical link,
   applicable recipient set, durable per-recipient outcome, and any required
   incident notification/outbox/Gmail evidence. A missing receipt is not
   presumed delivered.

## Operator checks and stop conditions

- If the guard is absent, unavailable, or cannot durably record `started`, the
  Telegram API is not called. Report that slot as blocked and preserve its
  original deadline; do not replay an expired brief.
- If a send result is ambiguous, leave it `delivery_unknown`. Reconcile with
  available provider evidence before any human-authorized recovery; never
  blindly replay it.
- If GitHub Pages returns an error, retain the sanitized error category and
  request ID. A request ID is diagnostic evidence, not proof that the 404 has
  been fixed. Do not issue an extra deployment to probe it.
- A Pages liveness response, green CI, an empty candidate list, no-op, or a
  closed issue does not prove Telegram delivery.
- Keep historical missed slots and receipts unchanged. Do not backfill expired
  reports, clear dedupe state, test-send to real recipients, or claim the
  service is restored without a natural per-recipient receipt.

## Local verification

Run the repository's targeted Python and Worker tests, Ruff, Mypy, and Worker
TypeScript checks in CI. Test doubles must intercept all Telegram and Worker
network calls. Do not dispatch a production workflow from validation.
