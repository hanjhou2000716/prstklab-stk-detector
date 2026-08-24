# Railway Gmail source-routing reliability

## Incident pattern

Gmail's `messages.get(format=full)` response may encode non-ASCII `From` and
`Subject` values as RFC 2047 encoded words.  Comparing those raw values with
the canonical Creator registry (for example `財經皓角`, `財女珍妮`, and `股癌`)
caused valid messages to be classified as `source_not_recognized`.  The
message was then placed in the bounded DLQ instead of producing a public
Creator observation.

## Fix

`railway-monitor/gmail_history_sync.py` decodes RFC 2047 headers before the
existing router and canonical parser run.  Malformed headers remain fail-soft:
the original bounded value is passed to the normal parser, which still owns
the source allow-list and DLQ decision.

The Railway Docker image also runs an import probe after copying the complete
standalone bundle.  A missing generated parser or dependency fails the image
build, rather than deploying a service that acknowledges mail while producing
zero observations.

## Verification

- RFC 2047 Creator `From` and `Subject` fixture routes through the existing
  parser (`tests/test_gmail_history_sync.py`).
- Generated Railway bundle remains synchronized with canonical `src/`.
- The post-copy Docker probe requires a callable `parse_external_email`.

This does not relax source allow-lists, verification, release gates, or
Creator's observe-only policy.
