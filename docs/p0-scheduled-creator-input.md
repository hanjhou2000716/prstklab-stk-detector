# Scheduled creator input boundary

`CREATOR_RECORDS_PATH` is an optional path to sanitized, derived Creator
Insight records. The scheduled workflow now filters private raw body,
attachment bytes, local paths, private URLs, and parser failure states before
putting any record into the market snapshot. A record received by Railway but
not safely parsed stays in the private DLQ and cannot leak into Pages.

The source file must remain outside `site/`; paths inside the Pages tree are
rejected. This is a defensive input boundary only: the briefing and release
validators still enforce parent release lineage, verification state, and
fail-closed alert evidence. Rollback is additive by reverting this filter;
existing release and Telegram gates remain unchanged.
