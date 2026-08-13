# P0-19 Gmail ingress evidence

## Contract

- Railway Gmail Pub/Sub ingress requires a bearer identity, configured audience
  and configured service account before parsing a payload.
- Request bodies are bounded to 256 KiB and only the Gmail history cursor is
  persisted; message bodies and attachments are excluded from the store.
- Cursor writes are idempotent, so a Railway restart or Pub/Sub replay does not
  create a second observation. Missing configuration, malformed envelopes and
  oversized requests fail closed.

## Verification

`tests/test_p0_19_gmail_ingress_contract.py` covers the size limit, malformed
payload, configuration boundary, cursor replay and privacy boundary. The
existing Railway gateway suite remains a required regression suite.

## Rollback

Revert the atomic P0-19 test/documentation commit. The existing ingress
implementation remains unchanged and continues to fail closed.
