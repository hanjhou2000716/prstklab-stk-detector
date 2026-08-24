# Creator Intelligence V2 — current state reconciliation (2026-08-24)

This is the current-state reconciliation after `main` commit
`c30399d55f4a08f91535df92fef155d714ab3b59` (PR #740). It supersedes older
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
| Pages release gate | manifest, hash and snapshot audit | external run 32662281221: 5/5 hashes verified | PASS-EXTERNAL |
| Railway heartbeat and Gmail Watch | `/health` projection | external run 32662281221: HTTP 200, heartbeat/Gmail/Watch healthy | PASS-EXTERNAL |
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
- External read-only run `32662281221` (2026-08-23T19:46Z): Pages ready with
  release `release-879015c6279c1ccc`, 5/5 artifact hashes and snapshot lineage
  verified; Railway heartbeat/Gmail/Watch healthy; Creator and FinancialJuice
  both reported `no_new_content`; GDELT explicitly reported `HTTP_429` with no
  stale cache and no promoted alert. The GDELT health callback remained
  healthy, so the monitor stayed running under bounded backoff.
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

## Latest external capture

Run `32662281221` was read-only: it made no Railway writes, changed no
configuration, and sent no Telegram messages. The resulting redacted artifact
is the source of truth for the evidence above. Because Creator/FJ had no new
mail and GDELT was rate-limited, the external completion debt remains open;
the system must not manufacture an event or claim a successful live delivery.

The newer read-only capture at `2026-08-24T01:19:25Z` is recorded in
[`docs/evidence/external-acceptance-2026-08-24T0119Z.md`](evidence/external-acceptance-2026-08-24T0119Z.md).
It confirms that the Gmail Watch lease is healthy through
`2026-08-30T20:05:00Z`, with no missing configuration, while Creator and
FinancialJuice remain explicit `no_new_content`. Pages is `ready` with 5/5
artifact hashes verified. GDELT remains `HTTP_429` under bounded backoff, so
the capture remains `NEEDS_REVERIFY`.

The subsequent read-only capture at `2026-08-24T01:39:31Z` is recorded in
[`docs/evidence/external-acceptance-2026-08-24T0139Z.md`](evidence/external-acceptance-2026-08-24T0139Z.md).
It confirms that Railway and the Gmail Watch remain healthy, Creator and
FinancialJuice remain explicit `no_new_content`, and Pages still verifies all
five declared artifacts. GDELT remains rate-limited with `HTTP_429`, so the
external completion debt remains open.

## Railway parser runtime recheck (2026-08-24)

The deployment bundle audit found a concrete dependency defect: the generated
Railway parser imports `bs4.BeautifulSoup` for HTML-only Creator and
FinancialJuice relays, but `railway-monitor/requirements.txt` did not declare
`beautifulsoup4`.  In the standalone Railway image this made the canonical
parser import fail, which correctly degraded ingress to
`parser_unavailable` but also meant no public observation could reach the
release pipeline.  The fix is committed in `563f584` and includes a runtime
requirements contract test; the generated parser remains the single canonical
bundle and is still checked by `scripts/sync_railway_canonical_parser.py`.

Local evidence after the fix: targeted Railway/Gmail contract suite `38
passed`; full repository suite `1383 passed`; canonical bundle check and
`compileall` passed.  A fresh Railway deploy and sanitized Gmail observation
are still required before changing the external rows above to
`PASS-EXTERNAL`.

The Gmail History adapter also now handles an expired history ID explicitly:
a `404` clears the invalid cursor, marks `history_cursor_expired` with
`history_gap=true`, and forces the next bounded Watch renewal to establish a
new baseline.  It does not pretend that messages in the expired interval were
recovered, and it prevents an infinite retry loop against the same cursor.

The latest read-only capture at `2026-08-24T02:00:50Z` is recorded in
[`docs/evidence/external-acceptance-2026-08-24T0200Z.md`](evidence/external-acceptance-2026-08-24T0200Z.md).
It verifies the same fail-closed boundary after the next Railway cycle:
Railway/Gmail/Gmail Watch remain healthy, Creator and FinancialJuice are
explicitly empty polls, Pages is `ready` with all five hashes verified, and
GDELT remains the only blocking upstream failure (`HTTP_429`).

The latest read-only capture at `2026-08-24T02:19:56Z` is recorded in
[`docs/evidence/external-acceptance-2026-08-24T0219Z.md`](evidence/external-acceptance-2026-08-24T0219Z.md).
It confirms Railway and Pages remain reachable, the Gmail Watch remains
healthy, and Creator/FinancialJuice remain explicit `no_new_content`. The
deployed monitor still exposes the pre-merge GDELT `event_scan=not_checked`
projection while the upstream returns `HTTP_429`; PR #744 contains the
fail-closed taxonomy correction. No production side effect was performed.

## Rollback

This document is additive. Reverting its PR does not change runtime behavior.
Runtime rollback remains the immutable previous `data-release` release; never
mix market, research, event, Creator, or FinancialJuice artifacts from separate
releases.
