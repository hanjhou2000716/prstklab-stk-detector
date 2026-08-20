# REQ-ADD-041：Railway canonical external-parser bundle

## Root cause

Railway 的 Root Directory 維持 `railway-monitor`，因此 image 內原本只有
provider metadata 與事件分類 bundle。Gmail router 可以辨識 FinancialJuice／Creator，
但無法載入 `src.external_source_parsers`；在 PR #640 已先改為 fail-closed，避免
錯誤確認後遺失郵件。

## 修復

- `scripts/sync_railway_canonical_parser.py` 依 AST 計算
  `src.external_source_parsers` 的 canonical import closure。
- 將 canonical parser、Creator registry、FinancialJuice contract、事件分類與必要
  config 產生至 `railway-monitor/src`、`railway-monitor/config`。
- 產物帶有來源檔 SHA-256；`--check` 會在來源與 bundle 漂移時失敗。
- Railway standalone image 因而使用同一套 canonical parser，不建立第二套分類或
  風險邏輯。bundle 只含公開程式與 config，不含 Gmail、Telegram 或任何 secret。

## 驗收

- root-only subprocess 可解析完整 FinancialJuice fixture 並產生一筆 public-safe
  observation。
- bundle generator parity、provider registry parity、shared classifier isolation
  測試通過。
- 解析失敗仍走 `parser_unavailable`／DLQ fail-closed 路徑；不會在 release gate 前
  發送通知。

## 部署與回滾

Railway 重新部署目前 `main` 即會透過 `COPY . .` 帶入生成 bundle。若 bundle
驗證或 runtime smoke 失敗，保留上一個成功 release，並回滾本 PR；不可改回靜默
確認郵件的舊行為。
