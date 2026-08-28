# MOPS incremental cache evidence — 2026-08-28

## Root cause

The Taiwan value scan fetched a bounded batch of MOPS history in one worker
process, but wrote `data/taiwan-mops-pristine-history.json` only after the
whole batch finished. A host-side timeout therefore discarded every ticker
verified earlier in that batch. Repeated scheduled runs could remain at the
same progress point and the public research release stayed stale.

## Fix

`src/mops_history.py` now writes the cache after each ticker attempt using a
sibling temporary file followed by an atomic replace. Successful records and
failure cooldown metadata both survive a later timeout. The final write is
retained to normalize legacy cache files, and no incomplete record is promoted
to a verified record.

## Verification

- `python -m pytest -q tests/test_mops_history.py` — 13 passed
- `uv run ruff check src/mops_history.py tests/test_mops_history.py` — passed
- `uv run mypy src/mops_history.py` — passed
- Regression fixture confirms the first verified ticker remains cached when a
  later worker is interrupted.

This is a persistence/reliability fix only. It does not relax MOPS history
completeness, candidate thresholds, release-gate checks, or notification
policy.
