# P5 Advice Gate contract

The advice gate is a fail-closed boundary for contextual research language.
It never authorizes orders, targets, guaranteed returns, or automatic trading.

## Required evidence

An eligible context must include fresh, quality-approved data, an independent
market cross-check, a valid policy, no candidate data gap, and an explicit
evidence list plus invalidation condition. A known general-research context is
accepted when no user risk profile is supplied.

When `backtest_release_contract` is present it must have both
`publication_state=ready` and `publish_eligible=true`. A blocked, incomplete,
or malformed P4 contract keeps the candidate in `observation_only` and records
`invalid_backtest_release`.

## Output

The gate returns the checks and blocking reasons together with a
`decision_support` object containing horizon, evidence, alternative scenario,
invalidation condition, confidence, and `actionable=false`. This makes the
research boundary explicit for JSON, Mini App cards, and later Telegram
summaries.

## Rollback

Revert this PR to restore the previous gate implementation. Existing release
and delivery gates remain fail-closed; no public artifact is deleted by this
change.
