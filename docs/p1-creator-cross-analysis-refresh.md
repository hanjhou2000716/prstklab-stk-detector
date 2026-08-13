# P1-01 Creator cross-analysis snapshot refresh

Creator 新內容只更新自己的 snapshot，並引用目前 `status=ready` 的 parent
release。刷新不會重跑或改寫 market、research、event 核心資料，也不會在
parent release invalid 時產生新的公開 artifact。

`refresh_creator_snapshot` 明確回傳 `available`、`no_new_content`、`stale` 或
`parent_release_unavailable`，並保留 parent 的三個 snapshot ID。超過 freshness
門檻時仍可讓 Mini App 顯示 stale，但不得把它當成即時市場證據或高風險警報。

回滾：撤回本 PR 即可停用 creator-only refresh；既有核心 release 不受影響。
