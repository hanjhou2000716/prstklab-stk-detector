# P1-05／P1-06：來源優先順序與 point-in-time 基本面

## 來源優先順序

`src/source_policy.py` 將每個市場的主來源、第二來源、允許時間差與價格差異集中管理。台股加權使用 TWSE＋TAIFEX，TPEx 使用 TPEx＋TWSE MIS，BTC／ETH 使用 Binance＋CoinGecko；原油、VIX 等資料也保留明確的第二來源需求。`evaluate_crosscheck()` 在缺來源、時間未對齊或價格差異超過門檻時只回傳未核對，不會把缺口升級成警報。每筆發布行情的 `quote_provenance` 同時帶出該政策與比較基準，確保 UI、release audit 與通知決策不會各自採用不同門檻。

## Point-in-time 基本面

`src/point_in_time.py` 保存不可變的財報觀測，欄位包含 `as_of`、實際 `published_at`、`fetched_at`、來源與快照雜湊。回測或研究以 `available_as_of()` 查詢時，只能讀取訊號時刻以前已公開的資料；`audit_no_lookahead()` 會將未來發布資料列為失敗，避免修正版財報或今天的基本面回填過去。

Point-in-time 查詢尚未替換既有研究抓取器；後續仍需將歷史資料查詢接入研究掃描，並把核對結果寫入 release manifest。來源政策本身已接入行情 provenance，現有專用 TWSE／TAIFEX、加密與公開市場核對器仍負責實際抓取與 fail-closed 決策。
