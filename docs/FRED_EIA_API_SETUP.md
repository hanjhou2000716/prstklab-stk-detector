# FRED／EIA API Key 申請與設定 SOP

## FRED

1. 開啟 [FRED API Keys](https://fred.stlouisfed.org/docs/api/api_key.html) 說明頁並登入／註冊 St. Louis Fed 帳號。
2. 在 API Key 頁面申請個人 key。只複製 key 本身，不要貼到 GitHub、Telegram 或程式碼。
3. 將 key 設為 GitHub Actions Secret：Repository → Settings → Secrets and variables → Actions → New repository secret，名稱固定為 `FRED_API_KEY`。
4. Railway 服務若要執行同一份監測器，也在 Variables 新增 `FRED_API_KEY`。

## EIA

1. 開啟 [EIA Open Data](https://www.eia.gov/opendata/register.php) 註冊信箱並申請 API key。
2. 將 key 設為 GitHub Actions Secret `EIA_API_KEY`，並在 Railway Variables 使用相同變數名稱。
3. 系統目前讀取 EIA petroleum spot weekly endpoint；key 缺少或請求失敗時只顯示資料缺口，不使用舊值臆測。

## 安全規則

- Key 只放在 GitHub Secrets／Railway Variables，不寫入 `.env.example`、README、日誌、Telegram 或 Mini App。
- 不要將 key 放進 URL、commit、截圖或 issue。若誤公開，立即在供應商頁面撤銷並重發。
- `FRED_API_KEY` 與 `EIA_API_KEY` 都是唯讀公開資料存取憑證；本系統不使用帳戶、交易或付款功能。
# FRED / EIA deployment placement

The variable names are exactly `FRED_API_KEY` and `EIA_API_KEY`.

## GitHub Actions (required for Phase 2 source scans)

Add both as repository **Actions Secrets**: `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`. These scans run in GitHub Actions, so this is the authoritative location for the scheduled research workflows.

## Railway (only if a Railway service runs the Phase 2 collectors)

Project Settings -> Shared Variables is acceptable, but each shared variable must be **shared** with the target service. Click `SHARE` beside `FRED_API_KEY` and `EIA_API_KEY`, then select the monitoring service. Alternatively add them in that service's `Variables` tab as references `${{ FRED_API_KEY }}` and `${{ EIA_API_KEY }}`. A warning icon on a Shared Variable normally means it has not been shared with a service yet.

The current Railway Jin10/GDELT bridge does not call the FRED or EIA collectors; its required variables remain `JIN10_MCP_TOKEN`, `GITHUB_DISPATCH_TOKEN`, `GITHUB_REPOSITORY`, and `EXTERNAL_ALERT_SHARED_SECRET`. Do not put API keys in Git, logs, Telegram messages or the Mini App.
