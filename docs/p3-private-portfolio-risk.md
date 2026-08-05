# P3-04 隔離式投資組合風控

`src/portfolio_risk.py` 只接受呼叫端暫存的手動持倉與報酬序列，計算集中度、
產業／國家／幣別曝險、加權 beta、歷史 VaR／CVaR。模組不登入券商、不讀取
帳戶、不保存持倉、不寫入 GitHub 或 Railway，也不提供買賣建議；輸出固定
`persisted=false` 與 `advice_allowed=false`。正式接入 Mini App 前仍需加入
獨立權限、加密儲存與刪除流程，不得把私人資料混入公開 Pages。
