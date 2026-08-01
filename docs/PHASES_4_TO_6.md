# Phases 4-6 implementation scope

This repository names the first three source phases explicitly. To keep the next work unambiguous, the following execution scope is now fixed:

## Phase 4: runtime source observability

Completed in PR #142/#143. Railway `/health` reports non-secret Jin10 and GDELT status, timestamps, counts and error classes. A provider outage is distinct from process liveness.

## Phase 5: fixed-sample walk-forward gate

The four-strategy research workflow must run only after a point-in-time archive audit passes. It uses disjoint training, validation and test windows, archived universe membership, historical fundamentals, transaction costs and survivorship checks. An incomplete archive must never produce a performance result.

## Phase 6: historical archive operations

The archive audit is independently runnable for Taiwan and US datasets and produces a JSON artifact even when incomplete. Required inputs are dated OHLCV files, point-in-time universe snapshots, point-in-time fundamental snapshots and an explicit delisted-symbols declaration. The audit workflow is manual until the archive is populated, preventing expected data gaps from generating recurring failure mail.

These phases produce research readiness evidence, not investment advice or trading instructions.
