# Mini App public interaction evidence

Read-only browser verification on 2026-08-29 used the public Pages release
`release-0c17992be7a6c05c` with `view=event`.

- The application loaded the risk, market, research, news and Creator insight
  sections without a network error.
- The release query was accepted and the event view opened the risk area.
- Expanding `來源健康狀態` succeeded and exposed the bounded source-health
  projection.
- The page had no horizontal overflow (`scrollWidth=1265`,
  `innerWidth=1280`).
- An alert identity not present in the same release produced the safe message
  `找不到此 alert 的同一 release 證據，暫不替換為其他事件。`; it did not
  substitute another event.

This proves safe public interaction and release-bound fallback. It does not
close the remaining Telegram WebView evidence debt; that requires a current
single-recipient message and an interaction through Telegram's WebView after
the reviewed PR chain is merged and Pages is deployed from `main`.
