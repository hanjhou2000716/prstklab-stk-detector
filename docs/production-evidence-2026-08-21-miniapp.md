# 公開 Mini App 生產證據（2026-08-21）

本文件記錄目前 `main` 所對應的公開 Pages release，只保存公開頁面可觀測資訊；不包含 Telegram chat ID、OAuth 憑證、私人郵件內容或任何 Secret。

## 驗證範圍

- 公開網址：`https://hanjhou2000716.github.io/prstklab-stk-detector/`
- 公開 manifest：`/data/release-manifest.json`
- 驗證方式：以 cache-busting query 讀取 manifest，並在 Pages WebView 讀取 DOM 與瀏覽器 console。
- 發布前仍由 `src.pages_release` 與 release manifest gate 驗證；`status=invalid` 不得覆蓋上一個成功版本。

## 公開 release lineage

| 欄位 | 值 |
|---|---|
| release_id | `release-faaa5b86acfc0db3` |
| created_at | `2026-08-21T09:06:30.804367+08:00` |
| market_snapshot_id | `d244146e6209880c` |
| research_snapshot_id | `research-8b8ec8f6e5ee51aa` |
| event_snapshot_id | `event-a889bf10a4141a3b` |
| creator_snapshot_id | `creator-4ea72d5e719d096e` |
| news_snapshot_id | `news-e63333c1720274ad` |
| manifest status | `ready` |
| creator status | `ready` |
| creator public status | `ready` |
| news status | `ready` |
| research freshness | `stale_fallback` |

Manifest 宣告的 market、research、event ledger、source health、news、creator release 與 creator insights artifact 均以 hash 綁定；Mini App 不應混用不同 release 的資料。

## DOM / UX 證據

公開頁面已觀測到：

- 「財經內容洞察」區塊與一筆公開摘要；狀態仍明確標示待核對，未暴露郵件原文或私人路徑。
- 市場風險區顯示「今日無重大市場事件，持續觀察」，與來源失敗分開。
- 來源健康區顯示「核心資料不足｜5 個來源有資料缺口」。
- 市場定時報告包含台股總經、台積電／半導體、科技產業、利率／匯率／黃金能源、加密市場與風險提醒。
- 研究區顯示「研究資料逾時，等待下一次全市場掃描」，不把缺資料誤列為無候選。
- 市場新聞提供台股／美股切換與公開來源連結。
- 頁尾文字為 `@2026 PRStK Lab & D.INV | All right reserved.`。
- 本次 WebView 驗證未觀測到瀏覽器 console error 或 warning。

## 尚未完成的外部 Gate

以下項目仍需在具備外部權限或實際來源後重新取得客觀證據，不能標記為 PASS：

- Railway Gmail OAuth／Pub/Sub 設定與實際 creator／FinancialJuice ingress。
- Railway canonical delivery secret migration（舊名稱仍需完成切換與撤銷確認）。
- GDELT 429 backoff／bounded-cache 在服務端的實際觀測。
- Creator／FinancialJuice 單一測試收件人的正式 receipt（不得廣播）。

在上述 Gate 完成前，資料不足、來源待核對與高風險通知的 fail-closed 規則保持不變。

## 回滾

本 PR 僅新增證據文件；若需回滾，撤回本文件即可，不會改變資料、release manifest、Mini App 或通知流程。
