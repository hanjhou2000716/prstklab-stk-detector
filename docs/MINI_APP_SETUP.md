# PRStK Telegram Mini App 啟用步驟

程式完成後，Telegram 訊息下方的按鈕會以 Mini App 模式在 Telegram 內開啟，而不是跳到外部瀏覽器。

## 需要在 BotFather 做一次設定

1. 合併程式後，在 GitHub **Actions** 手動執行 **Configure Telegram Mini App**；它會為你的私人聊天室設定Mini App選單入口。顯示名稱以目前Workflow與Telegram設定的正式驗收結果為準，不能只依README推論已完成改名。
2. 打開 `@BotFather`，選擇 `/mybots`，再選 `@PRStK_Lab_bot`。
3. 進入 **Bot Settings** → **Configure Mini App**，啟用 **Main Mini App**，並填入：`https://hanjhou2000716.github.io/prstklab-stk-detector/`。

完成後會有兩個入口：

- 每一則快報下方的 `📡 D.iNV Detector` 按鈕（需以實際測試訊息確認正式收件人看到的文字）。
- Bot 私人聊天室底部的選單按鈕／Bot 個人頁面的 Launch App。

GitHub Pages 網址必須維持 HTTPS，且快報需在使用者與 Bot 的私人聊天室中接收，才能使用 Inline Mini App 按鈕。

## 驗證方式

在 GitHub Actions 手動執行 **Scheduled market brief**，勾選 `force`。Telegram 收到的按鈕應直接在 App 內打開，頁面會依 Telegram 深／淺色主題調整並自動展開。
