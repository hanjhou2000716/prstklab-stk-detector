# REQ-ADD-024 health baseline state

The Railway `/health` payload now declares the GDELT `event_scan` and
market-sync components before the first poll completes. Both begin at
`not_checked`; the absence of a cycle is not represented as `no_event` or
`healthy`. Later cycles replace these values through the existing bounded
health projections.

This is additive and backwards compatible. Reverting the atomic commit only
removes the baseline keys; it does not alter polling, alert, or release gates.
