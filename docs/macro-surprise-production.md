# P2-03 總經 Surprise Engine 正式整合

正式 briefing pipeline 現在會把公布值、預期值、前值、修正、歷史標準差、
公布時間與來源 URL 傳入 `src.surprise_engine.calculate_surprise`。缺少必要欄位時
仍輸出 `insufficient_evidence`，不補值、不推測市場方向。

同一份 intelligence JSON 也會保存事件後可取得的市場價格觀測：

- `market_reaction.status`: `observed_only` 或 `not_available`
- `market_reaction.quotes`: ticker、變動幅度、freshness 與來源 URL
- `market_reaction.direction_confirmed`: 預設為 `false`
- `market_reaction.reason`: 說明尚未完成因果／同向核對的原因

價格觀測只是第一反應證據，不會因總經 surprise 或單一價格變動直接升級警報。
只有事件來源、第二來源及同市場同步核對都通過既有 release gate，才可進入通知流程。

## 回滾

撤回本 PR 即可移除 briefing 的市場第一反應欄位；既有總經 surprise 結果與
fail-closed advice gate 不受影響。
