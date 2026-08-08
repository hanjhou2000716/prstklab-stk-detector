# P5：情境式研究建議閘門

`src/advice_gate.py` 會檢查資料品質、報價新鮮度、第二來源核對、正式回測 release、候選資料完整度、policy 版本與風險脈絡。任一條件不符就固定回覆「目前資料不足，僅能列為觀察候選，暫不提供操作判斷」，不輸出買賣指令。

同一模組也產生候選解釋卡，列出通過／未通過條件、資料完整度、風險、訊號日期與失效條件，並保留法遵聲明。它可被 Mini App 與後續 paper portfolio 共用。

`src/paper_portfolio.py` 提供唯讀的 paper-observation 記錄。它保存發布時的
release/snapshot、可見價格、策略版本與 5/20/60 日觀察欄位；缺少價格時保留
`null`，不補造模擬成交。每筆資料固定標示 `paper_only=true`，不寫入私人持倉、
不下單，也不送入正式 Telegram。
