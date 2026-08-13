# 財經內容洞察：公開紀錄規則

`creator/public-records.json` 是已審閱的公開內容洞察輸入；它位於
`site/` 以外，排程只會在 release manifest 建立時將經驗證的衍生欄位
發布到 Mini App。

## 可保留的內容

- 公開作者／節目名稱、公開標題與公開網址。
- 明確標示為「來源主張」或「作者觀點」的簡短摘要。
- 主題、涵蓋市場與待核對的官方資料類別。
- `verification_state` 與來源核對狀態。

## 不可保留或發布的內容

- 原始 Gmail 本文、附件、message/thread ID、寄件或收件資訊。
- 私人網址、本機路徑、Cookie、Token 或任何帳號資訊。
- 未經官方或第二獨立來源核對的數字，作為 PRStK 的市場事實。

Creator 洞察是觀察與內容脈絡，不是事件證據：它不會影響高風險快訊、
選股候選或市場方向判定。只有經既有來源核對與市場證據流程確認的資料，
才可進入核心市場／事件管線。

## 新增一筆內容

每筆紀錄至少需要：

- `content_origin`：目前僅允許 `haojiao` 或 `gooaye`
- 穩定的 `episode_key`
- `episode_title`
- `source_url`（必須是公開 HTTPS 網址）
- `verification_state`
- `public_safe: true`

若要以外部的已清洗檔案覆蓋版本庫預設資料，可設定
`CREATOR_RECORDS_PATH`；該檔案仍必須位於 `site/` 之外，並會重新經過
隱私與來源驗證。沒有可用資料時，Creator lane 只顯示無內容／來源狀態，
不影響核心市場 release。
