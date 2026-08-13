# P0-17 Creator photo delivery

Production creator photo delivery is fail-closed for renderer/media failures:
an invalid or unavailable image is never sent as a blank card. The existing
transport-safe path records the failure and sends the bounded text notification
with the same deep link, making the degradation visible and retryable without
blocking other recipients.

The contract tests cover renderer failure, missing media and the resulting
delivery receipt. The renderer itself still requires Playwright/Chromium for a
real photo and validates dimensions and non-single-colour output.
