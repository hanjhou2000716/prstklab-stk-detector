# Pages 無效資料版本保護

`data-release` 是不可變的資料歷史，但市場／事件刷新可能先於完整研究掃描
寫入一個暫時不符合 production freshness 的版本。Pages 部署不再把這種預期的
fail-closed 結果當成 workflow failure：`src.pages_release` 會由新到舊檢查最多
100 個 immutable commits，並以 `src.release_manifest --require-production-research`
重新驗證每個候選版本。

- 找到最新有效版本：只發布該版本，後續 asset、release gate、runtime audit 與
  Pages upload 全部執行。
- 沒有有效版本：輸出 `pages_publish=skipped`、保留目前公開 Pages 版本，並以
  warning 記錄原因；不部署無效 manifest，也不觸發 Telegram。
- Git／資料分支本身不可讀：workflow 仍然失敗，因為這是需要修復的基礎設施錯誤，
  而不是可以安全忽略的資料新鮮度狀態。

回滾方式：撤回此 PR 即恢復原本的單一最新版本檢查；不修改 `main`、
`data-release` 或公開資料。要回到更早版本時，重新執行 Pages workflow，
由 immutable history 選取上一個通過 production gate 的 release。
