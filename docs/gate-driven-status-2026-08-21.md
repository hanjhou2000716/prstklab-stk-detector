# Gate-driven status ledger — 2026-08-21

這是目前 `main` 的中途稽核，不把「程式存在」或「PR 已合併」直接當成完成。狀態只有在目前可追溯的程式、測試與客觀運行證據都存在時才會標為 `PASS / LOCKED`。

## 目前基線

- Main HEAD：`72bfcc9989a8fb5d65065a6f38277ed0c901831e`（合併 PR #693）
- 公開 Pages release：`release-faaa5b86acfc0db3`，manifest `ready`
- 公開 Creator／News artifact：`ready`
- Railway `/health`：HTTP 200、monitor `running`、Jin10 `healthy`
- Railway GDELT：`HTTP_429`，bounded backoff；健康回呼 `HTTP_403`
- Railway Gmail/Creator ingress：`configuration_missing`
- 最新針對性測試：Haojiao sanitized fixture 8 passed
- 合併後主線完整回歸：1329 passed（另有 pytest cache 權限警告，不影響結果）
- 回歸 fixture：`tests/fixtures/haojiao-20260821-sanitized.json`；只含公開摘要，解析結果維持 `unverified`

## P0 traceability matrix

| Requirement | Implementation / evidence | Verification | Status |
|---|---|---|---|
| P0-01 Canonical Creator Provider Registry | `config/creator_providers.json`, `src/creator_provider_registry.py` | registry／unknown-provider tests | PASS / LOCKED |
| P0-02 Jenny Source Adapter + Parser | `src/creator_source_adapters.py`, creator pipeline | parser/privacy regression | PASS / LOCKED |
| P0-03 Attachment / Media Provenance | creator provenance and redaction contracts | attachment hash／privacy tests | PASS / LOCKED |
| P0-04 10:30 Morning Creator Batch | `src/schedule_contract.py`, scheduled workflow | schedule and point-in-time tests | PASS / LOCKED |
| P0-05 Creator Consensus V2 | `src/creator_consensus.py` | latest-per-creator and >=2 creator tests | PASS / LOCKED |
| P0-06 Consensus × PRStK Cross Analysis | `src/creator_correlation.py` | snapshot and stale-context tests | PASS / LOCKED |
| P0-07 Creator Public Artifact V2 | `src/creator_artifact.py`, release manifest | public hash/lineage checks | PASS / LOCKED |
| P0-08 Creator Mini App UX | `site/index.html`, `site/app.js` | public Pages DOM evidence | NEEDS_REVERIFY (WebView interaction evidence) |
| P0-09 FinancialJuice Compound Parser | `src/financialjuice_contract.py`, external parsers | compound/replay/privacy tests | PASS / LOCKED |
| P0-10 FJ >=8 Mandatory Policy | vendor priority is separate from PRStK risk | 7/8/9/10 boundary tests | PASS / LOCKED |
| P0-11 Cluster-aware Dedup | shared event/outbox ledger | duplicate/material-change tests | PASS / LOCKED |
| P0-12 FJ End-to-End Production Lane | scheduled delivery and release gate | no live sanitized Railway bundle | NEEDS_REVERIFY |
| P0-13 FJ Risk Card UI | source-health and Mini App cards | UI contract tests | PASS / LOCKED |
| P0-14 News Provider Registry | provider catalog and allow-list | registry tests | PASS / LOCKED |
| P0-15 Normalized NewsStory Contract | `src/news_contract.py` | schema/normalization tests | PASS / LOCKED |
| P0-16 News Interest Graph | `src/news_interest_graph.py` | graph evidence tests | PASS / LOCKED |
| P0-17 News Relevance Ranking | ranking policy and source tier | ranking fixtures | PASS / LOCKED |
| P0-18 News Deduplication | canonical key and cluster ledger | duplicate fixtures | PASS / LOCKED |
| P0-19 Frontend URL Security | URL allow-list and source labels | unsafe URL tests | PASS / LOCKED |
| P0-20 Market News Mini App UX | Taiwan/US tabs and five-item layout | layout/assets tests; public DOM | PASS / LOCKED |
| P0-21 Creator Telegram Rendering | release-gated creator notification path | local renderer/delivery tests; no live Creator receipt | NEEDS_REVERIFY |
| P0-22 Late Creator Delivery | late-arrival lifecycle and dedup contracts | local late-delivery tests; Gmail ingress absent | NEEDS_REVERIFY |
| P0-23 Gooaye Daily Behavior | provider registry and behavior policy | no live Gooaye ingress evidence | NEEDS_REVERIFY |
| P0-24 Observability | source health, creator/FJ counters and receipts | local contract + public health; live ingress absent | NEEDS_REVERIFY |
| P0-25 Failure Semantics | empty vs source failure, fail-closed alert gate | release/source-health tests | PASS / LOCKED |
| P0-26 Railway Architecture Cleanup | bounded adapters, health dispatch and runtime config | Railway monitor regression; live callback 403 remains visible | NEEDS_REVERIFY |
| P0-27 Release Contract | manifest hashes, snapshot lineage, publish-before-notify | Pages manifest `ready`, public artifact lineage | PASS / LOCKED |
| P0-28 Security / Privacy | redaction, no raw mail/private IDs, secret boundary | privacy/security suites and CodeQL | PASS / LOCKED |
| P0-29 Tests | unit, contract, offline E2E and CI gates | 109 targeted; 1328 full baseline | PASS / LOCKED |

## Regression ledger

| Regression ID | Symptom | Root cause / handling | Status |
|---|---|---|---|
| REG-RAILWAY-429 | GDELT rate limit | exponential bounded backoff and at-most-2h stale cache; no alert promotion | OPEN external / fail-closed |
| REG-RAILWAY-403 | GitHub health callback denied | callback is observability-only; local health remains authoritative and retry is bounded | OPEN external / non-blocking |
| REG-GMAIL-CONFIG | Creator/FJ no live mail | OAuth/PubSub variables absent; health reports configuration_missing, not no_event | OPEN external |
| REG-TELEGRAM-RECEIPT | Creator/FJ live receipt absent | requires one constrained recipient and valid release | OPEN external |

## Completion debt

| Debt ID | Description | Resolution needed | Status |
|---|---|---|---|
| DEBT-GMAIL-001 | Gmail OAuth/PubSub watch configuration | configure and validate Railway variables | OPEN |
| DEBT-GDELT-001 | GDELT recovery evidence | observe a successful poll after 429 backoff or documented outage | OPEN |
| DEBT-RAILWAY-001 | Canonical health callback permission | provision dispatch permission or approved callback path | OPEN |
| DEBT-TELEGRAM-001 | Creator/FJ constrained receipt | run one controlled recipient acceptance | OPEN |
| DEBT-UX-001 | Telegram WebView interaction evidence | execute non-broadcast interaction test | OPEN |

這些外部 debt 不會被標成 PASS，也不會放寬 release gate、資料新鮮度或高風險通知條件。核心市場與公開 Pages 可在 Creator/FJ 外部來源缺失時以 fail-soft 方式發布，但不能把缺失解釋成「沒有事件」。

## Preservation contracts

- PC-001 market refresh、PC-002 risk/event gate、PC-003 research release、PC-004 Pages manifest、PC-005 Telegram dedup、PC-006 Railway heartbeat、PC-007 privacy boundary 均由目前主線測試與公開 release 驗證保護。
- 本文件只增加可追溯性，不修改執行路徑；回滾方式為撤回本文件。
