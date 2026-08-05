# P2 事件聚類 metadata

`src/event_crosscheck.py` 會為非價格事件產生 `event_cluster_key`。它以
事件分類、人物／實體、地點、動作與兩小時發布時間窗計算，刻意排除來源
URL 與 provider，因此官方稿、Reuters 與 GDELT 對同一事件的描述可以進入
同一 cluster。

`event_cluster_key` 只是可追溯 metadata，不代表事件已核對，也不會放寬
通知規則。事件仍必須通過不同網域的第二來源或官方確認，以及需要時的
相關市場同步確認。每個 cluster 同時保留 `crosscheck_status`、來源 URL、
來源網域與 `source_trace.event_cluster_key`，Mini App 可用同一 key 顯示
事件版本歷史，避免多篇報導被誤認為多個獨立事件。
