# P2-06：人工回饋與誤報資料集

Mini App 可回報七種匿名標籤：正確、不相關、重複、方向錯誤、來源不足、太晚通知、不需要通知。`normalize_feedback()` 只保存事件 cluster ID、標籤、來源與時間，不保存帳號或私人投資資料。

`summary_feedback()` 只使用 `reviewed=true` 的回饋計算 precision、false-positive rate、太晚通知率、來源不足率與可用送達率。未審核回饋不會影響統計，`threshold_update_allowed` 固定為 false，避免個別回饋直接改變警報門檻。

回滾：撤回本 PR 即可停止回饋統計；既有事件與推播資料不受影響。