# P1：Mini App 靜態資產快取契約

Pages 發布前會執行 `python -m src.build_assets --root site --build-sha "$GITHUB_SHA"`。
腳本以 `app.js`、`styles.css` 與主視覺圖的 SHA-256 計算 deterministic asset version，
把 `site/index.html` 的 `__ASSET_VERSION__` 參照替換成該版本，並輸出
`site/asset-manifest.json`。瀏覽器因此會在 bundle 內容變更時取得新資產，而不依賴人工日期字串。

這是部署產物步驟，不會修改 GitHub `main` 上的來源 placeholder。若資產缺失或 index 未含
placeholder，建置會失敗且不應上傳 Pages artifact。回滾時使用上一個成功 release 的整個 site
artifact，不可只替換單一 JS/CSS 檔案。
