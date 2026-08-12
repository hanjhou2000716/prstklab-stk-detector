# P0 External event pipeline binding

`build_intelligence_context` 現在可接收 `external_observations`，並輸出同一事件
的 cluster、R0–R4 風險、通知資格與未滿足原因。這使 Mini App／後續 Telegram
流程能看到「等待核對」而非把新聞報告當成已確認快訊。

此 binding 不會放寬 Advice Gate；即使事件達 R3，沒有有效行情、發布或策略證據
仍維持 `observation_only`。
