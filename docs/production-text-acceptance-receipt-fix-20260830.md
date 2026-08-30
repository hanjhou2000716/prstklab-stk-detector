# Production text acceptance receipt fix

The controlled text acceptance workflow sent its single Telegram message
successfully, but labeled the receipt `text_acceptance`. The deployed Worker,
Supabase schema, and Railway rollback store accept the existing `production`,
`photo_smoke`, and `creator` receipt kinds only; the callback therefore
returned HTTP 400 after a successful delivery.

The workflow now records controlled text acceptance as the existing
`production` receipt kind with `delivery_mode: text`. This keeps the receipt
contract compatible across Cloudflare Worker, Supabase, and Railway without
resending the Telegram message or expanding the production receipt schema.

Verification:

- workflow contract tests require `DELIVERY_RECEIPT_KIND: production`;
- the full callback contract remains unchanged;
- no photo sender is introduced.

The failed run's Telegram message was already delivered once. Future runs
will persist the receipt through the existing release-gated callback path.
