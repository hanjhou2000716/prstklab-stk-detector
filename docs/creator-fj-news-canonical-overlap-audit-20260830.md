# Creator／FinancialJuice／News canonical overlap audit — 2026-08-30

## Scope

This audit records the migration follow-up after the zero-cost Gmail ingress
change in PR #824.  It is an integration checkpoint, not a claim that live
production acceptance has already passed.

## Canonical ownership

| Capability | Canonical owner | Boundary | Result |
|---|---|---|---|
| Creator provider registry | `config/creator_providers.json` + `src/creator_provider_registry.py` | Provider metadata and parser selection | single registry; bundled Railway copy is generated |
| Creator parsing | `src/creator_source_adapters.py` | Private Gmail input → public-safe structured observation | one parser path; episode identity is a content hash, never a Gmail message ID |
| Gmail state | `railway-monitor/supabase_email_store.py` | Private cursor/message state and public projection | Supabase-backed store; transport IDs are blocked from public JSON |
| FinancialJuice | `src/financialjuice_contract.py` + `src/financialjuice_priority.py` | Compound email fan-out and vendor-priority policy | one contract and one notification policy |
| News | `src/news_intelligence.py` + `src/news_feed_adapters.py` | Normalisation, ranking, dedupe and source health | existing canonical news path retained |
| Release/notification | existing release gate and scheduled delivery | publish-before-notify, receipts and Telegram | no bypass added |

## Findings and fixes in this checkpoint

1. The Gmail-to-Supabase public projection previously discarded Creator
   structured fields.  The projection now retains the reviewed title,
   takeaways, verification, correlation and attribution fields required by
   the Mini App while rejecting Gmail message/history/thread IDs and raw
   content.
2. The scheduled collection job now receives only the scoped
   `PUBLIC_OBSERVATIONS_SHARED_SECRET`; it is not a job-wide Telegram or
   repository credential.
3. Pub/Sub `historyId` is carried into the canonical Gmail history sync.  A
   missing baseline is handled fail-closed, and a consumed cursor is cleared
   after a healthy sync.
4. Creator episode keys are deterministic hashes of source and reviewed
   content.  Legacy raw message IDs are not emitted as public identity.
5. Public observation health counts are bounded and do not expose private
   records.

## Evidence captured

- Canonical overlap verifier: passed with zero duplicate-owner failures.
- Intelligence contract verifier: passed offline.
- Creator／FinancialJuice／News integration tests: **97 passed**.
- Supabase projection, Gmail gateway, history-sync, parser and email
  intelligence tests: **51 passed**.
- Scoped observation-secret client test: passed with the full targeted suite.
- Ruff on changed runtime/test paths and Python compile check: passed.

## Remaining gates

The following remain `NEEDS_REVERIFY` until the stacked PR is merged and the
external canary is run: a live Gmail Watch renewal, a real Pub/Sub delivery,
the current Pages release, Worker deployment, and a single-recipient Telegram
delivery receipt.  No production-wide notification is permitted as part of
this audit.

## Rollback

Revert the checkpoint PR to restore the previous public projection and cursor
handling.  Keep PR #824 and the Railway path available as the rollback route;
do not delete the Supabase data or overwrite a known-good release manifest.
