# Evidence — Creator media runtime (2026-08-25)

- The dispatch path now calls `validate_creator_media` before photo delivery.
- Invalid bytes are rejected and use text-only degradation.
- The private media root remains outside public artifacts and receipt payloads.
- Regression coverage exercises the runtime dispatch boundary, not just the
  standalone validator.
