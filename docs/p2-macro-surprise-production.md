# P2 Macro Surprise production contract

Briefing snapshots now pass partial macro observations to the existing
`surprise_engine` instead of dropping them when `expected` or `actual` is
missing. This keeps the output honest:

- no macro observation: `not_provided`;
- incomplete macro observation: `insufficient_evidence`;
- expected and actual present: `above_expectation`, `below_expectation`, or
  `in_line`;
- missing historical standard deviation leaves `surprise_z` as `null`.

The engine remains descriptive only. It never infers a market direction from a
macro surprise and cannot unlock advice or a high-risk alert by itself.

## Rollback

Revert this PR to restore the prior caller behaviour. No persisted data or
secret migration is needed.
