# 回測發布狀態與研究候選

研究頁以公開 release manifest 的 `backtest_publication_state` 為準：

- `ready`：可顯示已通過發布閘門的回測結果。
- 其他值（包含 `unavailable`、`pending`）：顯示「正式回測尚未發布；候選僅供研究觀察，不提供操作判斷」。

回測資料不足不等於沒有候選，也不等於風險不存在。正式 Advice Gate 仍必須等待 point-in-time 歷史資料、下市標的、公司行動與成本模型完成並通過 audit。任何 release 若未通過閘門，不能藉由前端提示或人工覆寫解鎖操作判斷。

## 驗證

1. 建立 `backtest_publication_state=unavailable` 的 manifest fixture。
2. 載入 Mini App 研究頁，確認提示文字可見。
3. 確認候選資料仍維持原本的研究觀察狀態，沒有被轉成正式建議。

## 回滾

移除此文件與對應 UI commit 即可回到上一版提示；不會改動 release manifest、來源核對或 Telegram 發送閘門。
