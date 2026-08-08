# Intelligence integration

The production context composer now calls the existing Market Impact Graph,
Macro Surprise Engine, Market Regime, Contagion and Stress Scenario modules.
`build_briefing_snapshot` embeds this context in the scheduled Mini App
briefing, so the card and the offline release-to-delivery dry run use the same
evidence contract.

Transmission paths remain conditional and the context returns
`observation_only` until the advice gate has complete, fresh and cross-checked
evidence. Missing macro expectations are not imputed. Stress results are
explicitly non-predictive and use only an equal-weight public watchlist when a
briefing has no private portfolio input; private holdings never enter the
public snapshot or Telegram delivery.
