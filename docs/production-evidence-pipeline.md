# Production evidence pipeline

每次市場刷新會先完成行情正規化，再綁定 `data_quality_score`、`quality_freshness`、`cross_checked`、`source_url`、`fetched_at` 與 `observation_id`。資料品質閘門遵循 fail-closed：

- 新鮮、可解析且完成必要交叉核對的報價才可標記 `alert_eligible=true`。
- 過期、延遲、來源未核對或缺少價格的卡片仍可顯示，但 `alert_eligible=false`，不能觸發 Telegram。
- 發布快照新增 `evidence.quotes` 與 `evidence.indices` 摘要，供 Mini App／來源健康狀態使用。
- 設定 `RAW_OBSERVATION_ROOT` 時，正規化行情會同步寫入不可變 raw observation store；未設定時不會在 CI 產生額外檔案。

## 驗證與回滾

`tests/test_production_evidence.py` 覆蓋新鮮交叉核對、過期但可見、品質摘要三種情境。若發布後發現品質門檻造成誤抑制，可回滾本 PR；既有 `market.json` 欄位保持向後相容，未知欄位不影響舊版 Mini App。
