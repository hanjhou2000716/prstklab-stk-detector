# Creator Intelligence / FinancialJuice / News overlap audit — 2026-08-29

This checkpoint is based on the latest `origin/main`
(`011103210538d3db0c0bf05f02f56b20d5cb9f67`) and the recovery branch
`checkpoint/continuation-20260829`. It reconciles the existing implementation
before adding new Creator/FJ/News work; it does not resurrect historical
branches or create a parallel pipeline.

## State snapshot

| Item | Observed state |
|---|---|
| Working branch | `feat/creator-fj-news-v4-20260829` |
| Recovery checkpoint | `checkpoint/continuation-20260829` → `83bff141` |
| Base | `origin/main` → `011103210538d3db0c0bf05f02f56b20d5cb9f67` |
| Tracked working tree | clean before this audit change |
| Existing local regression | 1,509 passed (main baseline) |
| Current branch full regression | 1,511 passed in 156.63s; storage probe startup hang fixed |
| Canonical-overlap audit | pass before this change |
| External acceptance | Read-only run `33252637471`: Worker healthy and Pages 7/7 artifact hashes matched; Railway returned 404 and external observation lineage is `NEEDS_REVERIFY` |

Untracked historical pytest and temporary directories are intentionally left
untouched. They are not part of this change and are never staged.

## Canonical ownership matrix

| Domain | Canonical producer | Runtime consumer | Local verification | State |
|---|---|---|---|---|
| Creator provider identity | `config/creator_providers.json`, `src/creator_provider_registry.py` | `src/creator_source_adapters.py`, `railway-monitor/email_router.py`, health and release | registry/schema/routing tests; canonical-overlap checker | PASS / LOCKED (offline) |
| Creator parsing and media provenance | `src/creator_source_adapters.py`, `src/creator_media_provenance.py` | Creator release and photo delivery | parser/privacy/media tests | PASS / LOCKED (offline) |
| Morning batch and consensus | `src/creator_morning_batch.py`, `src/creator_consensus.py` | scheduled release and Creator digest | 2/2, partial, late-arrival and divergence tests | PASS / LOCKED (offline) |
| FinancialJuice compound parsing | `src/external_source_parsers.py`, `src/financialjuice_contract.py` | external event pipeline | compound/replay/privacy tests | PASS / LOCKED (offline) |
| FinancialJuice priority | `src/financialjuice_priority.py`, `src/financialjuice_notification.py` | scheduled delivery and event ledger | 7/8/9/10 boundary and risk-separation tests | PASS / LOCKED (offline) |
| Shared event classification | `src/event_classifier.py` | FJ/news/live-event paths and event ledger | generated Railway bundle hash and integration tests | PASS / LOCKED (offline) |
| Market News registry/ranking | `src/news_intelligence.py`, `src/news_feed_adapters.py` | `src/risk_news.py`, release `news.json`, Mini App | provider, URL, relevance, diversity and dedup tests | PASS / LOCKED (offline) |
| Release and notification gate | `src/release_manifest.py`, `src/release_gate.py`, `src/scheduled_delivery.py` | Pages → Mini App → Telegram | manifest/hash/publish-before-notify tests | NEEDS_REVERIFY (external) |
| Delivery receipt persistence | `src/delivery_callback.py`, Cloudflare Worker/Supabase, Railway fallback | Telegram and Creator/FJ receipts | offline callback/Worker contract tests | NEEDS_REVERIFY (live canary) |

## Overlap findings and repair

1. `config/creator_providers.json` remains the only Creator allow-list. The
   Railway copy is generated/checked against it; no second Jenny or Gooaye
   identity table is introduced.
2. Creator identity is now selected only from sender/subject markers in both
   `src/email_intelligence.py` and `railway-monitor/email_router.py`. A quoted
   name in an arbitrary mail body cannot hijack an editorial parser. Unknown
   mail remains `invalid_source`/DLQ-safe.
3. Creator records remain editorial and never enter event evidence or upgrade
   PRStK risk. FinancialJuice vendor importance remains a notification
   priority and cannot rewrite the PRStK risk level.
4. `src/event_classifier.py` is the only shared classifier. News provider
   routing, relevance and URL safety remain separate from event evidence.
5. Creator and News are additive/fail-soft artifacts. A missing optional
   artifact cannot invalidate a valid market-risk release; a failed release
   gate still blocks Telegram.

## Verification evidence

The new identity-boundary regression is covered by:

```text
python -m pytest -q --basetemp=.tmp-creator-route-hardening \
  tests/test_email_intelligence.py \
  tests/test_railway_gmail_gateway.py \
  tests/test_creator_source_adapters.py \
  tests/test_creator_provider_registry.py
47 passed
```

The full local baseline and canonical-overlap checks remain required after the
atomic commit. Live Gmail, Railway, Pages and Telegram evidence is not
fabricated; those rows stay `NEEDS_REVERIFY` until a controlled canary exists.

The post-fix full regression completed with 1,511 tests passing. During the
first run, Gmail runtime startup exposed a Windows/OneDrive stall in
`tempfile.NamedTemporaryFile`; the storage probe now uses a deterministic
per-process sibling and atomic replace, and the Gmail runtime/storage suites
pass (8 tests).

The read-only external acceptance run `33252637471` verified the public Worker
health endpoint and the Pages release (`release-0c17992be7a6c05c`) with all 7
declared artifact hashes matching. The configured Railway hostname returned
HTTP 404, so no Gmail, persistence, observation-lineage, or delivery-receipt
claim is promoted to production evidence.

## Requirement reconciliation

The original P0-01…P0-29 registry remains authoritative in
`config/gate_evidence.json` and `docs/p0-requirement-traceability.md`. Existing
local locks are preserved, while external-only claims remain open. This audit
adds evidence for the P0-19 Gmail identity boundary without changing release,
privacy, or fail-closed thresholds.

## Rollback

Revert the atomic identity-boundary commit. This restores the prior routing
implementation without deleting release data, changing secrets, or altering
the Creator/FJ/News registries. The release gate and existing DLQ behavior
remain fail-closed during rollback.
