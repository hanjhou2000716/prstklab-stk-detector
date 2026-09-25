# Independent TAIFEX Day-Session Calendar

Taiwan cash-session status continues to use `pandas_market_calendars` with
`XTAI`. Taiwan index-futures day-session status is provided separately by
`src/taifex_calendar.py` from the reviewed official records in
`src/taifex_calendar_data.json`; it must never fall back to `XTAI` or a
weekday-only guess.

The checked-in 2026 schedule is based on TAIFEX's annual closure table and
incorporates the exchange's subsequent July 10 typhoon closure and September
25/28 closure notices. The adapter reports its version, coverage, official
source URLs and any closure reason. Dates beyond verified coverage, malformed
calendar data, or missing source metadata return `unverified` and block Taiwan
scheduled-delivery decisions. This is intentional: the current data covers
2026 only, so a future year's report remains blocked until that year's official
TAIFEX schedule has been reviewed and added.

## Annual maintenance

1. Obtain the new annual futures-market open/closed schedule from TAIFEX and
   record its document title, publication date, exact official URL, and
   document identifier in the JSON data.
2. Compare every listed non-trading weekday with the previous schedule and
   calendar data. Add subsequent official closure notices as separate source
   records with the affected date and reason; do not infer exceptional closure
   dates from TWSE or XTAI.
3. Extend the calendar unit tests with the new year's ordinary holidays and
   at least one official ad-hoc closure when one has occurred. Verify next
   trading dates at year boundaries.
4. Keep `verified_on` honest. It records when the checked-in annual source and
   currently known notices were reviewed; it does not imply the adapter is
   polling TAIFEX live for later notices.
5. Run the calendar, scheduled-obligation, digest-contract, and market-snapshot
   tests before merging. Never override an `unverified` decision for a live
   scheduled slot without first updating and reviewing the official source
   data.

An ad-hoc closure announced after `verified_on` cannot be detected by this
offline pinned calendar until the official notice is incorporated. The daily
schedule remains deterministic and independent of TAIFEX network availability;
release operators should update the pinned record promptly when TAIFEX posts a
new closure notice.
