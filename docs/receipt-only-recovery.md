# Receipt-only recovery

`receipt-only-recovery.yml` repairs a durable delivery receipt when Telegram
already accepted a controlled message but the callback failed afterward. It
requires an explicit confirmation and the original trace/release identifiers,
uses the existing `production` receipt contract, and never has a Telegram
token or a Telegram transport step.

The workflow is intentionally separate from the normal acceptance workflow so
recovery cannot resend a message. Use it only with the immutable values from a
failed run's masked Actions output.
