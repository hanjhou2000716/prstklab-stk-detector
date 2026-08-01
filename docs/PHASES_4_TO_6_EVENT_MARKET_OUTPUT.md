# 第 4～6 階段：事件、行情與輸出規格

## 第 4 階段：事件去重與永久帳本

`site/data/event-ledger.json` 是事件的可審計帳本，Railway 則可將
`EVENT_LEDGER_PATH` 指向持久化 Volume。GitHub Actions Cache 只負責短期
互斥鎖，不再是唯一的事件記憶。

每筆紀錄包含：

- `canonical_key`：由事件類型、主題、發生時間桶及人物／地點／動作指紋產生。
- `source_url`：移除 `www`、追蹤參數及 fragment 後的正規化 URL。
- `person_fingerprint`、`location_fingerprint`、`action_fingerprint`。
- `first_discovered_at`、`last_reminded_at`、`escalated`。
- `verified_sources`：已用於交叉核對的來源 URL。

帳本至少保留 30 天；相同事件換了新聞網址仍會收斂到同一 canonical key。
重大升級（例如警戒變高風險）可繞過一般冷卻時間，但仍會留下升級紀錄。

## 第 5 階段：市場交叉核對

行情卡新增統一欄位：來源、報價時間、盤中／最近收盤、是否已交叉核對。
預期來源配對如下：

| 市場 | 主要／次要來源 |
| --- | --- |
| 台股 | TWSE／TAIFEX |
| TPEx | TPEx／TWSE MIS 備援 |
| 美股指數 | Yahoo／另一公開市場來源 |
| BTC／ETH | Binance／CoinGecko |
| WTI／能源 | Yahoo／EIA 或其他公開來源 |
| VIX | Yahoo 歷史資料／可取得的官方資料 |

若次要來源缺漏、時間未對齊或價差超過檢查門檻，卡片仍保留，但
`cross_checked` 為 `false`；系統不會把未核對報價升級成高風險快訊。

## 第 6 階段：輸出與通知品質

重大事件與市場風險卡固定使用四段：

1. 事件：發生什麼事。
2. 為何重要：對利率、政策、供應鏈或風險偏好的實質意義。
3. 可能連動：可能傳導至哪些市場，不把相關性寫成因果。
4. 股市觀察：下一步要核對的價格、波動或官方更新。

每輪最多四個主題。Telegram 短訊息只保留：

`事件類型｜市場方向｜變動幅度｜風險等級`

完整摘要、原始 URL、來源網域、事件／核對時間、交叉核對市場與傳導說明
留在 Mini App。所有輸出仍固定附上：
「僅供公開資訊整理與教育性觀察，不構成投資建議。」

