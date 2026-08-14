# REQ-ADD-033：Railway Gmail registry bundle

## 根因

Railway 目前以 `railway-monitor` 為 root directory。這個部署映像沒有
repository-level `src` package，導致 `email_router` 的 canonical Creator
registry import 直接拋出 `ModuleNotFoundError`，健康端點因此把 Gmail 顯示成
未知失敗。

## 修復

- 在 `railway-monitor/creator_providers.json` 保存由 canonical registry 產生的
  public metadata bundle（只含 provider markers，不含帳號、token、收件人或信件內容）。
- `email_router` 在完整 checkout 優先使用 `src.creator_provider_registry`；只有
  standalone Railway root 缺少 `src` 時才讀取 bundle。
- bundle 缺失、格式錯誤或重複 ID 時立即 fail closed，不接受未識別來源。
- parser、事件分類、風險與推播政策仍由 canonical pipeline 擁有，bundle 不建立第二套邏輯。

## 驗證與限制

standalone root import、Gmail gateway、Ruff/Mypy/compileall 與完整回歸必須通過。
部署後 `/health` 應不再回報 `ModuleNotFoundError`；若 Gmail OAuth/PubSub 變數尚未
設定，狀態應是明確的 `configuration_missing`，而非假裝健康。回滾本 PR 即可
移除 bundle；不修改公開 release 或私有郵件資料。
