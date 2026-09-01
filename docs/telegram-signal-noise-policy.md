# Telegram Signal-to-Noise Policy

This policy is the presentation and selection boundary for realtime alerts.
It reuses the existing `EventLedger`, `Alert Budget`, release gate and
publish-before-notify path; it does not create a second delivery ledger.

## Investor-facing message

- `src.telegram_client.canonical_short_message` is the single public formatter.
- The internal `R0`–`R4` level is retained in event objects, receipts, the
  ledger and Mini App audit data, but is never emitted in Telegram text or
  photo captions.
- The risk colour dot remains visible. The message uses a topic and an
  evidence-grounded summary, capped at 30 characters. Generic labels such as
  “市場觀察” are removed when a real summary is available.
- FinancialJuice importance is shown as `FJ n/10` metadata only and cannot
  change the PRStK risk level.

## Theme de-duplication

`EventLedger.notification_theme_key` projects provider stories into a stable
investor theme (`fed-rate-outlook`, `us-semiconductor-policy`,
`middle-east-conflict`, or `<ticker>-price-move`). `theme_decision` records
every decision and applies a two-hour semantic window:

- the first qualifying material event is eligible;
- a new URL, provider, analyst or rewritten headline is suppressed with
  `same_theme_within_2h` while its evidence remains in the ledger/Mini App;
- official confirmation, risk upgrade, fact-version change, market
  confirmation, price escalation, direction reversal or systemic emergency
  can re-alert.

The existing delivery-volume budget remains separate and unchanged.

## Taiwan-session priority

During 08:45–13:30 Asia/Taipei, the selector ranks Taiwan holdings/index and
Taiwan policy first, semiconductor/AI exposure second, official US macro third,
and commentary-only discovery content as digest-only. A confirmed systemic R4
event bypasses this ordering. Scheduled selection uses the same theme lock, so
a scheduled brief cannot replay a realtime-delivered theme within two hours.

## Verification

`tests/test_notification_policy.py` covers cross-provider theme convergence,
two-hour suppression, official re-alerts, price escalation, commentary routing,
Taiwan priority and systemic bypass. Existing Telegram, EventLedger, monitor,
scheduled delivery, FinancialJuice and production E2E tests cover preservation
of receipts, release lineage, watchlist signals and recipient isolation.
