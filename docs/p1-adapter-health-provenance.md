# P1 Source Adapter 健康血緣

每個 Adapter 的健康快照會保留最近一次成功觀測的 `observation_id`、payload
hash 與 HTTP 狀態碼。這些欄位只描述可驗證的來源觀測，不會把健康狀態提升成
跨來源核對或即時行情；發送閘門仍由資料品質與 release gate 決定。發生失敗時，
最後成功血緣仍可供 Mini App 顯示，並與本輪失敗清楚分開。
