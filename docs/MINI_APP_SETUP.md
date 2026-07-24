# PRStK Telegram Mini App 啟用步驟

程式完成後，Telegram 訊息下方的按鈕會以 Mini App 模式在 Telegram 內開啟，而不是跳到外部瀏覽器。

## 需要在 BotFather 做一次設定

1. 打開 `@BotFather`，選擇 `/mybots`，再選 `@PRStK_Lab_bot`。
2. 進入 **Bot Settings** → **Menu Button**，將按鈕文字設為「開啟稜量 Mini App」。
3. 將網址填入：`https://hanjhou2000716.github.io/prstklab-stk-detector/`。
4. 進入 **Bot Settings** → **Configure Mini App**，啟用 **Main Mini App**，並填入同一個網址。

完成後會有兩個入口：

- 每一則快報下方的「開啟稜量 Mini App」按鈕。
- Bot 私人聊天室底部的選單按鈕／Bot 個人頁面的 Launch App。

GitHub Pages 網址必須維持 HTTPS，且快報需在使用者與 Bot 的私人聊天室中接收，才能使用 Inline Mini App 按鈕。

## 驗證方式

在 GitHub Actions 手動執行 **Scheduled market brief**，勾選 `force`。Telegram 收到的按鈕應直接在 App 內打開，頁面會依 Telegram 深／淺色主題調整並自動展開。
