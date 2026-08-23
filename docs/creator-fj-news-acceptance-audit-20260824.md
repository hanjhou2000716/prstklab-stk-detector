# Creator／FinancialJuice／新聞整合驗收稽核

本稽核 `scripts/verify_intelligence_contracts.py` 只使用固定 fixture，不連線
Gmail、Railway、GitHub Pages 或 Telegram。它驗證目前 canonical producer 已被
同一條公開資料契約串接：

- Creator registry 的 Jenny 顯示名稱為「財女珍妮」，10:30 morning lane 僅要求
  haojiao／jenny；Gooaye 保持 optional。
- Creator release 綁定 parent release、market／research／event snapshot，未知
  creator 會被丟棄，無效媒體降級為 text-only。
- FinancialJuice compound item 保留獨立 item ID；重要度 ≥8 可進 vendor-priority
  通知決策，但不改寫 PRStK 風險或虛構市場方向。
- 台股／美股新聞使用 provider registry 與市場相容性；Fed 不會進入台股分頁，
  SEC 故事可進入美股分頁，公開 URL 需為受信任 HTTPS 來源。

## 執行

```text
python scripts/verify_intelligence_contracts.py
```

這是離線 contract gate，不代表 Gmail Watch、Railway、Pages 或正式 Telegram
已完成外部驗收；那些仍須以限定收件者的 production acceptance evidence 另行確認。
