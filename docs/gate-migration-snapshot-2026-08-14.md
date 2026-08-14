# Gate-Driven v3 migration snapshot - 2026-08-14

This snapshot records the repository state before the next migration task. It
is a recovery checkpoint, not a production acceptance claim.

## Repository state

| Field | Value |
|---|---|
| Working branch | `feat/migration-state-snapshot` |
| Branch base | `feat/REQ-ADD-024-health-baseline-state` |
| Base PR | [#601](https://github.com/hanjhou2000716/prstklab-stk-detector/pull/601) |
| HEAD at snapshot | `a0365962c6611aa1521dda62adfb5de08a7a87b9` |
| Working tree before this snapshot | clean |
| Main merge policy | feature branches and PRs only; no automatic main merge |
| Protected side effects | no production broadcast, no secret changes, no automatic trade |

The branch contains the stacked Railway observability boundaries through
REQ-ADD-024. The existing feature commits are preserved; this task adds only
the audit snapshot and does not rewrite or reset them.

## Evidence captured before continuing

- PR #601 is open, non-draft, conflict-free.
- PR #601 checks are green: `test-and-dry-run`, CodeQL, dependency review, and
  SBOM (run `31802773449` / `31802773489`).
- Isolated full repository regression at HEAD `1415f90` completed with
  `1207 passed` in `121.49s`. The later documentation-only commit does not
  change executable code; the branch CI rerun also passed at `a036596`.
- Railway targeted suite reached `117 passed` for the health-baseline boundary.
- No live Railway, Pages, or Telegram acceptance was inferred from local or CI
  evidence.

## Current implementation reconciliation

| Area | State | Evidence / next gate |
|---|---|---|
| Market/research/event release contracts | PASS / LOCKED | Existing schema, invariant and release-gate tests |
| Alert lifecycle, budget and deduplication | PASS / LOCKED | Existing lifecycle and delivery tests |
| Railway cache, ledger, dispatch and retry boundaries | PASS / LOCKED (repository) | PRs #590–#596; live restart continuity remains external |
| Railway market-sync and GDELT health projections | PASS / LOCKED (repository) | PRs #597, #599, #600 |
| Railway preflight health baseline | PASS / LOCKED (repository) | PR #601; initial states are explicit `not_checked` |
| Source-health / Mini App release projection | NEEDS_REVERIFY | Must compare a public ready manifest and artifact hashes after deployment |
| Railway restart, volume and signed callback | NEEDS_REVERIFY | Requires controlled Railway environment and protected callback secret |
| Telegram single-recipient delivery receipt | NEEDS_REVERIFY | Requires an explicitly approved test recipient; dry-run remains green |
| Formal backtest / Advice Gate | NEEDS_REVERIFY | Existing contract remains observation-only until a valid backtest release |

## Active task and blockers

**Active task:** continue from the next unverified external gate without
reopening locked repository boundaries.

**External blockers:** Railway credentials/volume access, Pages public-release
propagation, and an approved single Telegram test recipient. These are not
repository failures and cannot be replaced with fabricated fixtures.

## Regression and debt preservation

- The authoritative ledgers remain `docs/gate-ledgers-2026-08-14.md` and
  `docs/gate-driven-state-2026-08-14.md`.
- Open external regressions/debts remain explicitly listed there; this snapshot
  does not close them.
- If a future task changes a locked boundary, it must reopen that task, rerun
  its original tests and record new impact evidence.

## Recovery

To recover this exact repository checkpoint, check out
`feat/migration-state-snapshot` at commit `a036596` and inspect the parent
commits. Do not copy individual release artifacts between releases; rollback
uses the previous successful release manifest.
