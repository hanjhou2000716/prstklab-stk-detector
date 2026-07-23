# PRStK Investment System

第一階段目標：從 GitHub Actions 安全地發出一則 Telegram 測試快報。

## 目前已完成的功能

- 30 字內快報驗證
- Telegram Inline Button（完整儀表板連結）
- 預設模擬模式，避免誤發送
- 可由 GitHub Actions 手動執行的測試工作流程
- 機敏資料使用 GitHub Secrets，不寫入程式碼

## 本機測試（不會發送）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest
python -m src.main
pytest -q
```

## 首次發送前的 Telegram 設定

1. 在 Telegram 開啟 `@olaf_spark_bot`，按下 **Start**，或傳送任意文字。
2. 取得 Bot Token：向 `@BotFather` 建立或管理 Bot 後複製 Token。
3. 取得 Chat ID：使用 Telegram Bot API 的 `getUpdates` 查詢；程式不會保存它。
4. 複製 `.env.example` 為 `.env`，填入 Token、Chat ID 與暫時的儀表板網址。
5. 執行下列指令才會真的發送：

```powershell
python -m src.main --send
```

## GitHub 設定

建立 GitHub repository 後，在 **Settings → Secrets and variables → Actions** 設定：

| 類型 | 名稱 | 內容 |
|---|---|---|
| Secret | `TELEGRAM_BOT_TOKEN` | BotFather 提供的 Token |
| Secret | `TELEGRAM_CHAT_ID` | 要接收快報的聊天 ID |
| Variable | `DASHBOARD_URL` | GitHub Pages 儀表板網址；第一階段可先填暫時網址 |

接著從 **Actions → PRStK Notification → Run workflow** 手動執行，即可發送第一則測試訊息。

## 儀表板

`site/` 包含 GitHub Pages 儀表板。第一次部署後，將 GitHub Pages 網址填入 `DASHBOARD_URL` 變數，Telegram 按鈕便會開啟儀表板。

## 安全提醒

- `.env` 已被排除，不會提交至 Git。
- Token 一旦外流，請立即到 BotFather 撤銷並重新產生。
- 第一階段不含市場資料、排程或任何交易功能。
