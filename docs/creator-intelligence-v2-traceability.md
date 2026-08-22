# Creator Intelligence V2：需求與證據追蹤

本文件是 Creator／FinancialJuice／News 升級的可追溯稽核表。`PASS` 只代表
本機程式、契約與測試有可重現證據；正式環境仍須另外完成 Pages、Gmail、Railway
與 Telegram 的 production acceptance。

| Requirement | Implementation | Verification | Evidence | Status |
|---|---|---|---|---|
| Canonical Creator registry | `config/creator_providers.json`、`src/creator_provider_registry.py` | registry／overlap tests | CI #656 | PASS |
| Jenny provider parser | `src/creator_source_adapters.py` (`jenny-template-v1`) | HTML、plain text、missing-section tests | `tests/test_creator_source_adapters.py` | PASS |
| Jenny structured fields | CSCO／NBIS／COHR／CBRS、content hash、template fingerprint | provider-field fixture | `tests/test_creator_source_adapters.py` | PASS |
| Private media boundary | `src/creator_media.py`、`src/creator_photo_delivery.py` | private-path／MIME／magic tests | creator media test suite | PASS |
| 10:30 morning batch | `src/creator_morning_batch.py` | cutoff、late-arrival、idempotency tests | creator morning test suite | PASS |
| Creator consensus V2 | `src/creator_consensus.py`、`src/creator_correlation.py` | multi-source and divergence tests | creator consensus test suite | PASS |
| Release-gated creator dispatch | `src/creator_dispatch.py`、`scheduled-brief.yml` | release mismatch／receipt tests | creator dispatch test suite | PASS |
| Reviewed Creator Railway ingress | `src/railway_observation_client.py`、`src/scheduled_delivery.py`、`scheduled-brief.yml` | sanitized Creator projection and release binding tests | 51 targeted tests | PASS |
| FinancialJuice compound parser | `src/external_source_parsers.py`、`src/financialjuice_contract.py` | compound／importance／cluster tests | FinancialJuice test suite | PASS |
| FinancialJuice live Gmail ingress | Gmail watch + Railway configuration | health endpoint and delivery receipt | live health currently reports missing Gmail variables | NEEDS_REVERIFY |
| Official news provider adapters | `src/news_feed_adapters.py`、`src/news_intelligence.py` | provider/domain/dedupe tests | news test suite | PASS |
| News production refresh | refresh workflow + public release | public artifact and freshness audit | must be rechecked after next refresh | NEEDS_REVERIFY |
| Canonical Railway bundle | `scripts/sync_railway_canonical_parser.py` | `--check` and overlap audit | CI #656 | PASS |
| Railway health secret migration | canonical `RAILWAY_STATUS_SHARED_SECRET` | live health callback | live service still reports legacy secret name | NEEDS_REVERIFY |

### Current stacked verification additions (2026-08-20)

- PR #659 adds the FinancialJuice priority projection to the existing scheduled
  release lane.  `vendor_importance >= 8` is auditable as a separate notification
  reason; it never changes the PRStK risk level or bypasses the release gate.
- PR #660 adds the FinancialJuice evidence rows to the existing 市場風險快訊
  card: source importance, PRStK Risk and second-source evidence remain separate.
- PR #661 carries reviewed ingress and delivery provenance end to end: received
  time, parser version, hashed observation identity, item/cluster keys, release
  and snapshot IDs, delivery status and notification reason.  Raw Gmail
  transport identifiers remain blocked at ingress.
- PR #661 CI evidence: quality/delivery dry-run, CodeQL, dependency review and
  SBOM all passed in the same workflow window (run `32401957171` and security
  run `32401957312`).
- Local targeted News／release／UI regression: `108 passed`; full CI is the
  authoritative gate.  Gmail／Railway／Pages／Telegram production acceptance
  remains `NEEDS_REVERIFY` until an external receipt is captured.

### Current continuation stack (2026-08-22)

The canonical continuation is represented by PRs #703–#707:

- #703 closes the offline Creator notification E2E lane.
- #704 exposes release-bound FinancialJuice evidence in the Mini App.
- #705 verifies the FinancialJuice panel through the browser contract.
- #706 adds the release-gated, single-recipient photo acceptance lane.
- #707 records redacted Railway/Pages external evidence, fails closed when the
  Railway delivery-secret migration flag is live, and includes the safe
  operator runbook without changing production configuration.

All five PRs remain stacked and must be reviewed in order. The local branch
checkpoint is green (`1350 passed` before the latest acceptance-contract test;
the targeted acceptance suite is green and full regression is rerun on this
branch), but the external acceptance state is still `NEEDS_REVERIFY` because
the live Railway service lacks Gmail watch configuration, GDELT is rate
limited, the health callback returns HTTP 403, and the runtime reports a
legacy delivery-secret migration requirement. This is deliberate fail-closed
behavior; it is not evidence that there was no new Creator or FinancialJuice
content.

The offline production E2E gate was rerun with the pinned Playwright Chromium
runtime installed: all contract checks passed, the renderer produced a
validated 1080x1350 card, and the mocked Telegram boundary reported delivered.
This remains offline evidence only; it does not replace a real single-recipient
production receipt.

## Fail-closed rules

- 未通過 provider parser、私有欄位或無法驗證的附件不得進入公開 Creator release。
- Creator 觀點永遠是 attributed editorial content，不會直接變成 PRStK 風險或交易訊號。
- Gmail、Railway、Pages 或 Telegram 的外部驗證缺證據時，狀態維持
  `NEEDS_REVERIFY`，不能宣稱 production 完成。
- 不把檔案存在、單元測試通過或 PR 建立當成正式上線證據。

## 後續驗收

1. 合併 #655 後先確認 canonical Railway bundle 在 main 重新產生。
2. 合併 #656 後執行一次 `refresh-dashboard`，保存 release manifest、Pages、Railway
   health 與 delivery receipt 的同一組 release／snapshot ID。
3. Gmail 來源完成變數設定後，再以單一測試收件人驗證 Jenny／FinancialJuice 的
   受控推播；未完成前不得廣播。
