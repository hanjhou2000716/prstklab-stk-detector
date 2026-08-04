# P0-04：發布 Manifest 與完整性閘門

`src.release_manifest` 會把市場、研究與事件三份公開 JSON 綁定成同一個
不可變發布單位。Manifest 會保存 `release_id`、三個 snapshot ID、政策／
schema 版本與每個檔案的 SHA-256；任何缺檔、解析失敗、快照不一致或 hash
被修改都會產生 `status=invalid`，不會被當成可推播版本。

## 產生與驗證

```powershell
python -m src.release_manifest
python -m src.release_manifest --root . --output site/data/release-manifest.json
```

`ready` 是可以交給後續發布／通知閘門的唯一狀態；`invalid` 只代表缺口已
被明確揭露，不能解讀成市場沒有事件或研究沒有候選。

Mini App 先讀 `data/release-manifest.json`，確認狀態、逐一驗證所有 artifact
hash，再載入 `market.json`。因此不會把新行情和舊研究資料拼成同一頁；驗證
失敗時只顯示「發布資料不完整」，並等待下一個成功 release。

## Rollback

發布器應保留上一份 `ready` manifest。新 manifest 失敗時不覆蓋上一份成功
資料；若需要回復，重新發布上一個 `release_id` 對應的完整 artifact 集合，
不可只回復單一 JSON。Telegram 通知必須在後續 P0-05 的發布驗證通過後才送出。
