# Creator release identity

The public release ID now includes a hash of the sanitized Creator Insight
input.  A changed creator record set therefore creates a new immutable release
instead of reusing the market/research release ID.  Derived lineage fields
(`parent_release_id`, creator `release_id`) are excluded from this seed to
avoid a circular hash while the creator artifact is bound to its parent.

This prevents a Pages cache or Telegram deep link from silently serving a
different creator payload under an unchanged release identifier.
