# Railway runtime reliability notes

## SQLite health-thread isolation

The monitor loop owns its long-lived SQLite connection.  Railway's threaded
health and delivery callback handlers now open a short-lived connection owned by
the requesting thread, with a bounded busy timeout.  This prevents
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be used
in that same thread` from turning `/health`, delivery history, or receipt
callbacks into 500 responses.

## Source failure observability

Creator and FinancialJuice health projections now expose only bounded failure
reason counters and the latest reason.  This distinguishes a quiet source from
known-template parser failures and unrecognised mail without exposing message
bodies, sender addresses, or transport IDs.

## GDELT rate limiting

GDELT 429 responses remain fail-closed and keep the existing persisted backoff
and cache policy.  Expected rate limiting is logged as a single bounded warning
instead of a traceback on every poll; non-rate-limit failures still retain the
full server-side exception log for diagnosis.

Rollback: revert this change.  No schema migration is required; the additional
health fields are additive and older consumers may ignore them.
