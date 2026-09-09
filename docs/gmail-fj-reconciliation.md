# FinancialJuice Gmail 即時補查契約

FinancialJuice 的正式處理路徑只有一套：Gmail Pub/Sub 推送、現有
`gmail-history-sync` 工作流、既有 parser、候選判定與既有通知流程。外部補查
只負責喚醒同一個同步工作流，不另建 parser、sender 或 ledger。

## 唯一外部補查工作

在既有 cron-job.org 工作中使用每 5 分鐘一次的排程，時區使用
`Asia/Taipei`，以 GitHub Repository Dispatch 呼叫：

```json
{
  "event_type": "gmail-history-sync",
  "client_payload": {
    "notify": true,
    "force": false,
    "trigger_kind": "cron-job.org"
  }
}
```

工作只需提供既有 GitHub dispatch 授權；Token、Repository、Gmail OAuth、
Supabase 與 Telegram 憑證不得放入 URL、request body、文件或 repository。
不要傳入人工歷史游標；工作流會從 Supabase 的持久化 `pending_history_id`
與 `last_history_id` 讀取待處理狀態。Pub/Sub 與補查同時抵達時，由資料庫狀態及
工作流 concurrency 合併，不能以單次 request 的 history ID 作為唯一可靠佇列。

## 狀態語義

- `last_push_received_at`：只在驗證後收到 Pub/Sub 時寫入。
- `last_sync_started_at`／`last_sync_completed_at`：只在同步工作開始／完成時寫入。
- `dispatch_requested`：只代表 GitHub 已接受同步請求，不代表同步完成。
- `processing`：同步工作已取用該待處理事件。
- `completed`：同步及候選判定已完成；失敗則保留待重試狀態。

只有同步可靠完成，才推進 Gmail history cursor 並清除 pending hint。解析或
候選完成不會回填推送時間；`Watch active` 也不等於 `push_delivery_verified`。
公開 Pages 只顯示去識別化的狀態、計數、時間與原因。

## 驗收

每次補查都必須留下同步開始／完成時間、候選診斷與通知決策。`notify=false`
只可用於正式鏈路驗證，不取得正式 claim、不更新成功投遞基準、不建立 Telegram
attempt；過期或缺少來源時間的郵件只保存診斷，不補發。
