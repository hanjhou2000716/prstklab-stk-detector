## P3 Market Regime Evidence in Briefings

依賴：#482（`feat/p3-alert-budget-scheduled-delivery`）

- 定時報告的 Market Regime 改由已取得且可用的跨市場報價建立因子：trend、breadth、volatility、rates、usd、gold、oil、crypto。
- stale／delayed／unavailable／failed 報價不再參與風控因子，避免過期數據製造市場狀態。
- 缺少因子時保留 `missing_factors` 與 `insufficient_evidence`，不以單一指數平均值冒充完整 regime。

驗證：`python -m pytest -q tests/test_briefing_cards.py tests/test_market_regime.py`（8 passed）。

回滾：撤回本 PR 即可回到原有 briefing 因子組裝；不變更行情來源或警報門檻。
