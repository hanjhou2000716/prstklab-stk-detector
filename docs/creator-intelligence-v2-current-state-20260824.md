# Creator Intelligence V2 — current state reconciliation (2026-08-24)

This is the current-state reconciliation after `main` commit
`b4ac1c8844413d8a2a0152ef34e90b43cc400549` (PR #739). It supersedes older
acceptance notes that pre-date the Gmail Watch and delivery-receipt fixes. A
local contract is marked `PASS-LOCAL`; a production statement is only marked
`PASS-EXTERNAL` when the corresponding public or Railway evidence exists.

## Requirement matrix

| Requirement group | Implementation / verification | Current evidence | Status |
|---|---|---|---|
| Canonical Creator registry | `src/creator_provider_registry.py`; registry and overlap tests | CI and offline canonical audit | PASS-LOCAL |
| Jenny editorial identity and structured parser | `src/creator_source_adapters.py`; provider fixtures | `jenny-template-v2` tests and parser audit | PASS-LOCAL |
| Jenny media provenance and fail-closed fallback | `src/creator_media_provenance.py`, `src/creator_media.py` | media MIME/path/magic tests | PASS-LOCAL |
| 10:30 Haojiao/Jenny batch | `src/creator_morning_batch.py` | complete/partial/late/idempotency tests | PASS-LOCAL |
| Creator Consensus V2 | `src/creator_consensus.py`, `src/creator_correlation.py` | divergence/latest-per-creator tests | PASS-LOCAL |
| Creator × PRStK alignment | `src/creator_intelligence_pipeline.py` | offline intelligence E2E | PASS-LOCAL |
| Creator public artifact and Mini App section | `src/creator_artifact.py`, `site/app.js` | Mini App asset/browser contracts | PASS-LOCAL |
| Creator real Gmail observation | Railway Gmail Watch and sanitized ingress | current health reports `no_new_content`; no mail was fabricated | NEEDS-REVERIFY |
| Creator production delivery receipt | `src/creator_dispatch.py`, scheduled release lane | no real Creator event in current poll | NEEDS-REVERIFY |
| FinancialJuice compound parser | `src/external_source_parsers.py`, `src/financialjuice_contract.py` | compound parser and item-boundary tests | PASS-LOCAL |
| FinancialJuice ≥8 vendor-priority policy | `src/financialjuice_priority.py` | threshold/separation tests | PASS-LOCAL |
| FinancialJuice risk separation | `src/financialjuice_contract.py` and event projection | vendor importance never changes PRStK risk | PASS-LOCAL |
| FinancialJuice dedupe/replay | delivery contract and notification E2E | partial retry and replay suppression tests | PASS-LOCAL |
| FinancialJuice production receipt | release-gated notification lane | current poll reports `no_new_content` | NEEDS-REVERIFY |
| News provider registry and market routing | `src/news_feed_adapters.py`, `src/news_intelligence.py` | provider/domain/ranking/dedupe tests | PASS-LOCAL |
| News public refresh | scheduled/refresh workflow and Pages artifacts | public release is ready; freshness is a separate live observation | NEEDS-REVERIFY |
| Pages release gate | manifest, hash and snapshot audit | external run 32661041562: 5/5 hashes verified | PASS-EXTERNAL |
| Railway heartbeat and Gmail Watch | `/health` projection | external run 32661041562: HTTP 200, heartbeat/Gmail/Watch healthy | PASS-EXTERNAL |
| Telegram generic photo delivery | production photo acceptance workflow | controlled single-recipient receipt delivered | PASS-EXTERNAL |
| Telegram Creator/FJ event delivery | release-gated domain lanes | no qualifying live event captured | NEEDS-REVERIFY |
| GDELT discovery health | bounded backoff and stale-cache path | provider returned HTTP 429; no alert was promoted | NEEDS-REVERIFY |
| Publish-before-notify and durable lineage | release manifest, delivery callback | merged-main tests and receipt lineage | PASS-LOCAL |
| Security/privacy boundary | redaction, URL/MIME checks, no raw mail/IDs | security CI, contract tests, acceptance artifact | PASS-LOCAL |

## Evidence references

- Full merged-main regression before the documentation-only reconciliation:
  `1375 passed in 78.46s`.
- PR #739 CI run `32661260305`: full test-and-dry-run, coverage, Ruff, Mypy,
  overlap/provenance, Mini App, Telegram configuration, and offline release
  acceptance all passed.
- External read-only run `32661041562`: Pages ready with artifact hashes and
  snapshot lineage verified; Railway/Gmail/Watch healthy; delivery state is
  interpreted as a receipt state; GDELT is explicitly `failed` with `HTTP_429`.
- The redacted snapshot is retained in the workflow artifact; this document
  contains no secret, raw email, recipient ID, or Telegram response body.

## Regression and completion debt

| ID | Description | State | Required next evidence |
|---|---|---|---|
| REG-EXT-001 | GDELT upstream rate limit | OPEN / fail-closed | successful or bounded stale-cache observation after retry window |
| DEBT-EXT-001 | Creator real observation not yet captured | OPEN | sanitized live Gmail observation and release-bound receipt |
| DEBT-EXT-002 | FinancialJuice real observation not yet captured | OPEN | sanitized live Gmail observation and release-bound receipt |
| DEBT-EXT-003 | News live provider freshness/split not rechecked in this capture | OPEN | next refresh artifact and provider-health evidence |

These items are deliberately not reclassified as “no event” or “complete”. A
provider failure, an empty poll, and a verified absence of an event remain
different states in the public contract.

## Rollback

This document is additive. Reverting its PR does not change runtime behavior.
Runtime rollback remains the immutable previous `data-release` release; never
mix market, research, event, Creator, or FinancialJuice artifacts from separate
releases.
