# Railway Gmail ingress observability

The Railway health endpoint now exposes a bounded, privacy-safe Gmail
projection. It answers whether the watch is configured and alive, whether
messages are waiting for parsing, and whether the parser has sent items to
the dead-letter queue.

Public fields include:

- watch status, expiration, and missing configuration variable names;
- observation count, last ingress/sync timestamps, and parser error count;
- `queue_pending_count` and `dead_letter_count`;
- `history_cursor_present` (a boolean, never the Gmail history ID).

The endpoint never exposes Gmail message/history IDs, sender addresses, mail
bodies, OAuth values, Pub/Sub tokens, or attachment content. A quiet inbox is
represented separately from parser/provider failure so the Mini App can show
「本輪無事件」 without implying that the source is healthy when the watch is
stale or configuration is missing.

Pending counts are derived from private SQLite rows whose parser state is
`received`, `queued`, or `pending`. Dead-letter counts are terminal parser
failures. Counts are projected as non-negative integers and malformed values
fail closed to zero.
