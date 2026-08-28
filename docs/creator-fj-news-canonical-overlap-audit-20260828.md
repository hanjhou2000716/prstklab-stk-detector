# Creator／FinancialJuice／News canonical overlap audit — 2026-08-28

## Snapshot

This audit is based on the current mainline after PR #802 and PR #805
(`41470dd4`). The receipt backend change is
additive; it does not create a second parser, classifier, release producer or
Telegram dispatcher.  The existing PR is [#804](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/804).

The audit is intentionally evidence-driven.  Local contract evidence is not
treated as live Railway, Pages, Gmail or Telegram acceptance evidence.

## Canonical ownership matrix

| Capability | Canonical producer | Runtime consumer | Local evidence | External status |
|---|---|---|---|---|
| Creator provider identity and sanitized parsing | `config/creator_providers.json`, `src/creator_provider_registry.py`, `src/creator_source_adapters.py` | Gmail adapter → creator release | parser/privacy/DLQ tests; overlap checker | NEEDS_REVERIFY |
| Creator consensus and correlation | `src/creator_consensus.py`, `src/creator_correlation.py` | briefing and creator artifact | latest-per-creator/divergence tests | PASS (offline) |
| Creator public release | `src/creator_intelligence_pipeline.py`, `src/creator_release.py`, `src/creator_artifact.py` | release manifest and Mini App | lineage/hash/privacy tests | NEEDS_REVERIFY |
| FinancialJuice parsing and vendor priority | `src/financialjuice_contract.py`, `src/financialjuice_priority.py`, `src/external_source_parsers.py` | external event projection | compound, threshold, replay tests | NEEDS_REVERIFY |
| News provider identity and routing | `src/news_intelligence.py`, `src/news_feed_adapters.py` | regional News artifact | provider scope/health/dedup tests | PASS (offline) |
| Shared news/live event classification | `src/event_classifier.py`, `src/news_intelligence.py`, `src/external_event_pipeline.py` | event ledger, lifecycle and release | canonical integration regression tests | PASS (offline) |
| Release and notification gate | `src/release_manifest.py`, `src/release_gate.py`, `src/telegram_client.py` | Pages → card → Telegram | release-gate and dry-run tests | NEEDS_REVERIFY |
| Delivery receipt persistence | `src/delivery_callback.py`, `worker/src/index.ts`, `supabase/migrations/202608280001_delivery_receipt_events.sql` | Worker/Supabase preferred, Railway bounded fallback | callback/worker contract tests; public Worker health 200 | NEEDS_REVERIFY for valid receipt canary |

## Overlap decision

There is one canonical path for each responsibility:

1. `config/creator_providers.json` is the only Creator allow-list.
2. FinancialJuice vendor importance is a notification-priority attribute; it
   cannot raise `prstk_risk_level` or bypass release gates.
3. `src/event_classifier.py` is the only shared classifier.  Scheduled news
   and live events pass the same bounded evidence fields; regional routing is a
   separate concern.
4. Reuters and GDELT are now known corroboration/discovery identities, but are
   explicitly disabled as official feeds.  This prevents an unverified URL or
   discovery endpoint from silently becoming official evidence.
5. Creator editorial records never enter `source_evidence` and can never set
   `is_investment_signal=true`.
6. `src/delivery_callback.py` selects the Cloudflare Worker/Supabase receipt
   endpoint when configured and retains Railway as a bounded fallback.  This
   is a transport replacement, not a second notification policy.

## Required gates still open

- Apply/verify the Supabase migration and run a single recipient receipt
  canary. Until that evidence exists, receipt persistence is not a production
  acceptance claim.
- The repository `DASHBOARD_URL` now points to the verified Pages project path;
  the prior `/prstk-lab/` value returned 404 for the manifest.
- Obtain a live Pages release manifest whose hashes match the release gate.
- Capture a current sanitized Gmail Watch/Creator and FinancialJuice
  observation; `no_new_content` is not proof of a successful content poll.
- Capture a successful post-backoff GDELT result or an explicitly bounded
  stale-cache observation.  HTTP 429 remains fail-closed.
- Keep Telegram tests restricted to a designated single test chat; never use
  a broad subscriber list for acceptance.

## Verification performed for this checkpoint

- `python scripts/verify_canonical_overlap.py` — pass.
- `python scripts/sync_railway_canonical_parser.py --check` — pass.
- `python scripts/sync_railway_shared_classifier.py --check` — pass.
- `python scripts/verify_intelligence_contracts.py` — pass (offline; external
  acceptance remains separate).
- `tests/test_canonical_intelligence_integration.py` — covers provider identity,
  shared classifier inputs, and Creator evidence isolation.

## Rollback

Revert the additive receipt commit and this audit/test change; keep the prior
Railway callback path and existing release gate.  Do not delete release
artifacts or alter the canonical Creator/FJ/News registries during rollback.
