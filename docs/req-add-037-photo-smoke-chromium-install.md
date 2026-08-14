# REQ-ADD-037：圖卡 Smoke Test 的 Chromium 安裝邊界

## 問題

限定單一收件人的圖卡驗證在 GitHub Actions 停留於 Playwright
`--with-deps` 安裝步驟，無法進入 renderer、Telegram 或 Railway receipt。

## 修復

- `ubuntu-latest` 使用 runner 已提供的 Chromium 系統相依套件。
- Smoke workflow 改用 `python -m playwright install chromium`，避免在工作流程中啟動可能長時間阻塞的 apt 相依套件安裝。
- 安裝步驟設置 10 分鐘上限；超時時 workflow 失敗且不會送出圖片。

## 安全邊界

這只影響明確指定 `photo_test=true` 且帶有單一 `test_chat_id` 的驗證流程；正式通知仍維持 renderer、release gate 與 fail-closed 規則。

## 驗證與回滾

驗證應確認步驟能進入 `src.photo_smoke_test`，並在 Telegram sendPhoto 後保存 Railway receipt。若 runner 缺少系統相依套件，回滾本次 workflow 變更並改用預先配置 Chromium 的 runner image；不得改回無限等待的安裝方式。
