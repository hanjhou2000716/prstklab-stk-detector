# P2-01：事件來源目錄

`src/event_catalog.py` 是所有公開事件來源的單一登錄表。每個來源都標示：來源層級、類別、公開端點、更新間隔、是否能單獨觸發警報與保存策略。

官方來源（Fed、BLS、BEA、ECB、SEC、CISA、WHO、GDACS、USGS、TWSE/MOPS）只在 `official_confirmed=true` 時可觸發；GDELT、Reuters、Google News 是線索層，必須有第二來源核對，不能單獨升級高風險事件。付費全文、登入頁、隱藏 API 與逆向端點不在目錄內。

## 使用規則

- `source_catalog()` 提供可供 Mini App／健康狀態頁使用的可追溯登錄資料。
- `sources_for_category()` 依事件類別挑選核對來源。
- `alert_source_is_allowed()` 是通知前的 fail-closed 閘門。
- 更新頻率是建議輪詢頻率，實際輪詢仍須遵守各來源限流與失敗退避。

回滾：撤回本 PR 即可移除目錄；既有來源抓取不會被刪除。後續 P2-02 會把此目錄接到事件聚類與去重帳本。