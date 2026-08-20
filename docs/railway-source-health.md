# Railway source health projection

The Railway `/health` endpoint now separates transport health from source
health. This prevents a healthy Pub/Sub watch from being mistaken for a
successfully parsed or delivered intelligence item.

## Components

- `gmail`: watch, cursor and ingress transport only.
- `creator`: sanitized Creator observations and parse/DLQ counters.
- `financialjuice`: sanitized FinancialJuice observations, importance `>=8`
  count, pending cluster count and release decision state.
- `news`: the Actions-plane news producer status. Railway reports
  `not_checked` until a release snapshot supplies its provider health; it does
  not invent a live news result.

All projections contain bounded counters, timestamps and state labels only.
Gmail message IDs, sender addresses, raw bodies and credentials remain inside
the private Railway store and are never returned by `/health`.

The source states are intentionally distinct:

- `healthy`: at least one parsed/public observation and no recorded failure;
- `degraded`: observations exist but at least one parse/DLQ failure exists;
- `failed`: failures exist without a parsed observation;
- `no_new_content`: the source has not produced a new observation;
- `not_checked`: no source evidence has been evaluated yet.

`financialjuice.decision` is `awaiting_confirmation` while public items still
lack official confirmation. It is not a Telegram risk decision and does not
override the release gate or market-synchronisation policy.
