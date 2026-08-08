# Mini App deep links

Telegram buttons include `alert`, `release`, and `view` query values. The
router compares the requested release with the public manifest before looking
up an alert. A mismatch or missing alert produces a safe archive/missing view;
it never silently opens a different event.
