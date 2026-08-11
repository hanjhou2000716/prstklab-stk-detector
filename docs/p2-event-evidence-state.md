# P2 事件證據狀態契約

新聞與即時事件共用同一個證據狀態。`discovery` 與 `single_source` 仍會留在
Mini App 與事件帳本，但不能被當成已核對事件；`pending_crosscheck` 明確顯示
仍在等待核對。只有 `corroborated` 或 `official_confirmed` 才具備足夠的來源
證據，重大／黑天鵝快訊仍需另外通過市場同步與 Alert Budget。

每筆事件會保存 `evidence_state`、`evidence_reason`、`evidence_domains` 與
`evidence_sufficient`。因此使用者能區分「等待第二來源」和「等待市場同步」，
而不是只看到一則沒有推播的新聞。

回滾：移除本契約與整合呼叫即可，既有 `crosscheck_status` 欄位保持相容。
