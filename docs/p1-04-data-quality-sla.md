# P1-04：資料品質與 SLA 分數

`src/data_quality.py` 將每個來源的可用率、延遲、新鮮度、完整度、跨來源一致性、解析信心與連續失敗轉成 `data_quality_score`（0–100）。

## 權重

| 因子 | 權重 |
| --- | ---: |
| availability | 25 |
| latency | 10 |
| freshness | 20 |
| completeness | 15 |
| cross-source agreement | 15 |
| parsing confidence | 10 |
| failure streak | 5 |

缺欄位不會被當成滿分。資料可以繼續在 Mini App 顯示，但品質不足時會被 gate 阻擋：

- `allow_display`：永遠允許顯示，並保留缺口／逾時狀態。
- `allow_alert`：分數達 70、來源健康、資料新鮮、非 stale／delayed，且完成必要交叉核對。
- `allow_research`：分數達 80、來源健康、資料未過期；不要求每個研究欄位都一定有第二來源。

這些 gate 是 fail closed：無法證明資料新鮮或核對完成時，不觸發警報、不進入研究候選，不把缺資料解釋成低風險。

## 回滾與後續

本 PR 只新增純函式品質分數，不改變既有工作流輸出；回滾即可恢復原有 source health。後續 P1-05 會把這些分數接入各市場的官方／第二來源核對與發布閘門。

## 測試

`tests/test_data_quality.py` 使用固定時間與假來源，覆蓋健康、逾時、未交叉核對、來源失敗與自訂門檻。