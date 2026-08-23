# Creator／FinancialJuice／News Migration Snapshot — 2026-08-24

這份快照是追加任務的 overlap audit，不重新建立第二套架構，也不把
「程式存在」誤報成正式上線。Canonical owner 維持：

- Creator identity：`config/creator_providers.json` → `src/creator_provider_registry.py`
- External mail parsing：`src/external_source_parsers.py`
- Market news：`src/news_intelligence.py` → `src/news_feed_adapters.py`
- Release：`src/release_manifest.py` → `src/release_gate.py`
- Delivery：`src/telegram_client.py`、`src/scheduled_delivery.py`
- Railway transport／health：`railway-monitor/` extracted boundaries

## Repository snapshot

| 項目 | 證據 |
|---|---|
| Baseline main | `5f5e18c502492bedc2273d486704949cb734621c` |
| Current branch | `fix/railway-gmail-gdelt-runtime-resilience` |
| Current HEAD | `fed3318` |
| Open stack | #729 → #730 → #731 |
| Working tree | clean after commit |
| Full local regression | `1370 passed in 80.08s` |
| PR #731 CI | test-and-dry-run／Ruff／Mypy／CodeQL／SBOM／dependency review all pass |

## P0 traceability

| Requirement | Canonical implementation | Verification | Status |
|---|---|---|---|
| P0-01 provider registry | `config/creator_providers.json`, `src/creator_provider_registry.py` | registry／bundle parity tests | PASS / LOCKED |
| P0-02 Jenny parser | `src/creator_source_adapters.py` | sanitized template／unsupported-template tests | PASS / LOCKED |
| P0-03 media provenance | `src/creator_media.py`, `src/creator_media_provenance.py` | invalid bytes／hash／text-only tests | PASS / LOCKED |
| P0-04 10:30 batch | `src/creator_morning_batch.py`, `src/creator_dispatch.py` | 2/2、partial、late、replay tests | PASS / LOCKED |
| P0-05 consensus V2 | `src/creator_consensus.py` | latest-per-creator／mixed／alias tests | PASS / LOCKED |
| P0-06 PRStK cross analysis | `src/creator_correlation.py` | stale／missing evidence tests | PASS / LOCKED |
| P0-07 public creator artifact | `src/creator_artifact.py`, `src/creator_release.py` | lineage／privacy／hash tests | PASS / LOCKED |
| P0-08 Creator Mini App | `site/app.js`, creator UI contracts | browser/layout/empty-state tests | PASS / LOCKED |
| P0-09 FJ compound parser | `src/financialjuice_contract.py`, `src/external_source_parsers.py` | two-item independent envelope tests | PASS / LOCKED |
| P0-10 FJ ≥8 policy | `src/financialjuice_priority.py` | 7/8/9/10 boundary tests | PASS / LOCKED |
| P0-11 cluster-aware dedup | event identity／notification identity modules | replay／cross-source dedup tests | PASS / LOCKED |
| P0-12 FJ production lane | Railway Gmail → release → Telegram | external acceptance required | NEEDS_REVERIFY |
| P0-13 FJ risk card | release projection／Mini App card | UI and risk-separation tests | PASS / LOCKED |
| P0-14–18 News registry／story／graph／rank／dedup | `src/news_intelligence.py`, `src/news_feed_adapters.py` | provider, scope, relevance, dedup tests | PASS / LOCKED |
| P0-19 URL security | release-provided provider allowlist | HTTPS/domain blocking tests | PASS / LOCKED |
| P0-20 market-news UX | `site/app.js` | Taiwan/US badges and responsive tests | PASS / LOCKED |
| P0-21–23 Creator delivery／late／Gooaye | `src/creator_notification.py`, `src/creator_photo_delivery.py` | mocked photo/digest/late tests | PASS / LOCKED (offline) |
| P0-24 observability | source health／delivery receipts／Railway health | local contract tests; live capture pending | NEEDS_REVERIFY |
| P0-25 failure semantics | explicit healthy/no-content/stale/failed states | failure-isolation tests | PASS / LOCKED |
| P0-26 Railway extraction | `railway-monitor/*` boundaries | compile/import and local boundary tests | NEEDS_REVERIFY (live packaging) |
| P0-27 release contract | manifest/hash/snapshot/release gate | mixed-release and publish-before-notify tests | PASS / LOCKED (external recheck pending) |
| P0-28 security/privacy | privacy filters, secret boundary, URL policy | CodeQL/SBOM/privacy tests | PASS / LOCKED |
| P0-29 regression suite | `tests/`, quality workflow | 1370 local + green PR CI | PASS / LOCKED (main post-merge pending) |

## External acceptance boundary

The latest read-only Railway/Pages capture is intentionally not promoted to
PASS. Pages served a `ready` manifest with matching hashes; Railway reported a
GDELT `invalid_json` and a Gmail `GmailIngressError`. PR #731 fixes the two
repository-side causes (persistent GDELT cooldown and optional Pub/Sub
audience-header handling), but the live service must be redeployed before the
same workflow can provide new evidence. The capture is recorded in
`docs/evidence/external-acceptance-2026-08-24-pr731.md`; no production Telegram
broadcast was performed by this checkpoint.

Required post-merge sequence:

1. Deploy the merged stack to Railway and confirm `/health` reports the new
   Gmail error labels and restored GDELT cooldown state.
2. Run the read-only external acceptance workflow and verify Pages manifest,
   release IDs and artifact hashes.
3. Process one controlled Gmail event (or a sanitized production-like fixture
   marked `SIMULATED`) and verify the release gate before delivery.
4. If an actual production Telegram test is explicitly authorized, use one
   test recipient only and retain the redacted delivery receipt.

Until those steps are complete, the overall migration state remains
`NEEDS_REVERIFY`; it must not be described as production-complete.
