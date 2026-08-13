# FinancialJuice contract

FinancialJuice is a discovery/relay source (`source_tier=discovery`). The
adapter preserves its original headline, Chinese translation, AI commentary,
possible impact and vendor importance as attributed metadata. It never treats
the vendor's 10/10 score as a PRStK risk level.

Risk mapping is evidence-gated:

- no official confirmation and no market synchronisation: `R2`, pending;
- official confirmation or at least two independent corroborating sources:
  `R3`;
- `R4` only when official confirmation **and** a related market movement are
  both present and time-aligned.

The Mini App receives `等待官方核對` and/or `等待市場同步` as explicit pending
reasons. Missing evidence cannot become a high-risk Telegram alert.
