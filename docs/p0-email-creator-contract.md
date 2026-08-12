# P0 Email／Creator Intelligence Contract

本 PR 建立 Gmail transport 與 FinancialJuice／Haojiao／Gooaye content
origin 的第一層契約。它不連線 Gmail、不保存 raw body，也不會自行推播。

## 安全邊界

- EmailObservation 只保存 message/thread/history ID、雜湊、時間、解析狀態與來源路由。
- 原始郵件與附件不得寫入 `site/data`、Pages、Git commit、PR 描述或 CI log。
- 未知寄件者明確標為 `invalid_source`，後續可進 DLQ；不可當成已核對事件。
- CreatorInsight 將 `claims` 與 `opinions` 分開，`verification_state` 預設 `unverified`。
- 這個契約尚未宣稱 Gmail Watch、Pub/Sub 或 Railway webhook 已啟用；那些是後續 P0 基礎設施 PR。

## 驗證

`python -m pytest -q tests/test_email_intelligence.py`

## 回滾

撤回本 PR 即可移除新增契約；既有市場、研究與事件資料不受影響。
