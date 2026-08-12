# P0 Gmail Watch／PubSub ingress

本 PR 建立 Gmail Watch 的安全入口契約：驗證上游已驗證的 Bearer 身分、限制
request body、只解碼 Gmail notification metadata，並以 durable cursor 形狀處理
重播與 stale history ID。它不會在沒有 OAuth／PubSub 設定時假裝健康，也不會保存
raw Gmail body。

## 狀態與恢復

- 無 cursor：`full_sync`。
- stale／invalid cursor：`full_sync`，不猜測遺失的郵件。
- 有效 cursor：`incremental`。
- 重複 history ID 會被去重；單頁超過上限會 fail closed。

## 尚未宣稱完成

Gmail Watch renewal、Google OAuth、Pub/Sub JWT 實際驗證、Railway durable storage、
parser/DLQ 與 Telegram 發送需要後續 PR；本 PR 只固定可測試的入口契約。

## 回滾

撤回本 PR 即可移除 ingress primitives，不影響既有市場／研究／事件流程。
