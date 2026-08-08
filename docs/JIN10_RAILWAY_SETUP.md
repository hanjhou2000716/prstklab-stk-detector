# 金十外部快訊與 Railway 設定

這份指南會把金十資料放在 Railway 的監測器中，再把已篩選、已簽章的事件送到 PRStK 的 GitHub 工作流程。金十 Token、GitHub Token 與共用密鑰都只放在 Railway Variables，不能放在 GitHub Pages、Telegram 或程式碼中。

## 1. 申請金十 Token

1. 前往 [金十數據智能開放平台](https://mcp.jin10.com/app/doc.html)。
2. 登入金十帳號，選擇「管理 TOKEN」並啟用 MCP Token。
3. 複製 Token 後先妥善保存；不要貼進 GitHub Issue、程式碼或聊天訊息。
4. 確認你的方案可使用所需資料。金十目前公開文件描述的是資料查詢能力；若沒有官方快訊推播，Railway 監測器會採輪詢方式取得新資料。

## 2. 建立 GitHub 的兩項安全資料

### 共用密鑰

在本機 PowerShell 產生一組長密鑰：

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

到 GitHub repository 的 **Settings → Secrets and variables → Actions → Secrets**，新增：

| 名稱 | 用途 |
|---|---|
| `EXTERNAL_ALERT_SHARED_SECRET` | 驗證 Railway 傳入的 HMAC 簽章 |

### 專用 Fine-grained Token

到 GitHub 個人設定的 **Developer settings → Personal access tokens → Fine-grained tokens**：

1. 建立新 Token，例如 `prstk-external-alert-dispatch`。
2. Repository access 選 **Only select repositories**，只選 `prstklab-stk-detector`。
3. Repository permissions 只給 **Contents: Read and write**。
4. 設定到期日，建議 90 天；到期前再輪替。
5. 複製 Token。它只會顯示一次，之後放到 Railway，不要放在 GitHub Secrets。

## 3. 建立 Railway 帳號與空白服務

1. 前往 [Railway](https://railway.app/)，以 GitHub 帳號登入。
2. 建立 Project，選擇 **Empty Project**。
3. 新增一個 Service；下一階段會把外部監測器程式部署到這個 Service。
4. 在 Service 的 **Variables** 新增以下值：

| Variable | 值 |
|---|---|
| `JIN10_MCP_TOKEN` | 第 1 步取得的金十 Token |
| `GITHUB_DISPATCH_TOKEN` | 第 2 步建立的 Fine-grained Token |
| `EXTERNAL_ALERT_SHARED_SECRET` | 與 GitHub Secret 完全相同的共用密鑰 |
| `GITHUB_REPOSITORY` | `hanjhou2000716/prstklab-stk-detector` |

不要勾選公開顯示 Variable，也不要把這些值寫入 Dockerfile、Git repository 或前端環境變數。

## 4. Railway 傳送事件的格式

Railway 只在事件符合重大門檻、去重後才呼叫 GitHub。它要送到：

```text
POST https://api.github.com/repos/hanjhou2000716/prstklab-stk-detector/dispatches
```

Headers：

```text
Accept: application/vnd.github+json
Authorization: Bearer <GITHUB_DISPATCH_TOKEN>
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Body：

```json
{
  "event_type": "external-market-alert",
  "client_payload": {
    "source": "jin10",
    "event_id": "jin10-unique-event-id",
    "category": "macro",
    "summary": "CPI 高於預期，市場波動擴大",
    "occurred_at": "2026-07-26T08:30:00+08:00",
    "signature": "sha256=<HMAC-SHA256>"
  }
}
```

簽章的原始文字必須完全依此順序，以換行連接：

```text
jin10
jin10-unique-event-id
macro
CPI 高於預期，市場波動擴大
2026-07-26T08:30:00+08:00
```

Railway 用 `EXTERNAL_ALERT_SHARED_SECRET` 對上方文字做 HMAC-SHA256，並在 `signature` 加上 `sha256=` 前綴。

## 5. GitHub 端的保護規則

系統只接受來源為 `jin10` 的事件，且必須符合：

- 分類限於 `fed`、`macro`、`policy`、`conflict`、`semiconductor`、`market`。
- 必須有格式正確的事件 ID 與 ISO 8601 發生時間。
- 簽章必須正確。
- Telegram caption 必須小於等於 40 個 Unicode 字元；圖片、按鈕與 caption 必須同一則訊息。
- 同一個事件 ID 只會發送一次。
- 驗證成功後才刷新市場資料、更新 Mini App、部署 Pages 與發送 Telegram。

## 6. 下一步

完成本頁的帳號與 Variables 設定後，再部署 Railway 監測器。監測器應設定為每分鐘輪詢、以事件 ID 去重、同類快訊設 15 至 30 分鐘冷卻，並且只放行重大事件。
