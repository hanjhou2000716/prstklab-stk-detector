# Production research universe contract

Production research is fail-closed on the resolved universe, not on the number
of rows that happen to be returned by a scan. Every scan summary now records:

- `universe_mode`: `full` or `bounded`
- `universe_expected`: resolved pool size before slicing
- `universe_scanned`: rows requested in this run
- `universe_completed`: rows with usable observations
- `universe_failed`: rows that failed acquisition or parsing

The report is publishable only when every source is `full`, the scanned count
covers the expected pool, all records complete without failures, and every
scan state is `complete`. A bounded, legacy, partial, or missing summary is
retained as a diagnostic artifact but cannot replace the last-known-good
production release. This prevents a manual 30-row smoke run from being labeled
as a full-market research result.

Value-quality scans also expose the resolved pool and history progress. A
Taiwan value scan may remain `building` while MOPS history is being cached;
formal candidates from completed records remain visible only when the report
contract permits them, and incomplete history never becomes a production
release claim.
