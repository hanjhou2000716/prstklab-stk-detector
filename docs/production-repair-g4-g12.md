# Production Repair G4–G12

本次修復以 `origin/main` 的 `a5c3280e` 為基準，將公開 Mini App 與通知路徑重新對齊產品契約。

## 需求對照

- REQ-001／REQ-005：公開 Mini App 移除自訂報告與 Creator Insight 區段、導覽入口及 `report-client.js` 載入；Creator 後端 parser、儲存與 release contract 保留。
- REQ-002／REQ-003：風險待推播原因放入「系統分析資料」；定時報告的 correlation、intelligence、外部快訊及紙上追蹤共用單一技術 disclosure。
- REQ-004：release loader 同時 hydrate `snapshot.research_report`；失敗刷新時保留 hash 綁定的上一成功版本，清楚標示資料降級與最後成功時間，不將 stale 候選當作 live。
- REQ-006：新聞排名先保留來源多樣性，再以剩餘安全且去重的候選填滿上限；不足五筆時只顯示實際筆數。
- REQ-007：Scheduled、Emergency、FinancialJuice 及官方市場事件的正式 production sender 使用 Telegram `sendMessage`；每位收件人仍有 release／snapshot／observation 綁定的 delivery receipt。Creator 私有例外仍可使用既有 photo path。

## 回滾

撤回本 PR 即可回到前一個已驗證的 release；不修改公開資料，不刪除 Creator backend 或既有 photo client。

## 驗證

局部驗證包含 Mini App contract、研究 loader、新聞多樣性／填充、Scheduled／Official／Emergency text delivery 與 receipt tests。完整 repository regression、CI、Pages／Worker 部署及 production acceptance 必須在 PR 合併後以最新 main 重新執行。
