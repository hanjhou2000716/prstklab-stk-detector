# P2：事件情報來源與 Surprise Engine

`src/event_source_catalog.py` 將官方事實來源與 GDELT／Reuters 等發現層分開登錄，並為每個來源保存更新頻率、可接受的新鮮度與是否能單獨觸發警報。`catalog_health()` 會把未掃描來源列成明確資料缺口，不再把「沒有事件」和「沒有掃到」混為一談。

`src/surprise_engine.py` 計算公布值相對預期值、前值及歷史標準差的偏離，輸出 `above_expectation`／`below_expectation`／`in_line`，但固定把市場方向標為 `not_determined`；市場方向必須在後續由報價與第二來源核對後確認。
