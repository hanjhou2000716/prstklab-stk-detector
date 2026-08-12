# Creator delivery in the offline intelligence dry-run

The external-intelligence dry-run now exercises the creator notification
contract after the creator artifact is built. It verifies that a public-safe
episode with a ready parent release is eligible for a text-only delivery when
no renderer media is available. No Telegram API, recipient, Gmail credential,
or network call is used.

The result includes the durable `notification_key`, explicit `media_mode`, and
the release-gate decision. This keeps the offline gate representative of the
production decision boundary without sending a message.
