# Actions external acceptance evidence

The read-only `External acceptance (read-only)` workflow was executed from
`feat/workflow-secret-scope-20260829` in run `33257561281` after the optional
Railway observation handling fix.

- Worker health: HTTP 200 (`prstk-api.hanjhou2000716.workers.dev`).
- Public Pages manifest: HTTP 200, `status=ready`.
- Release lineage: `release-0c17992be7a6c05c`, with market, research and event
  snapshot IDs present.
- Artifact audit: 7 declared / 7 verified; zero missing, mismatched or lineage
  errors.
- Railway health and observation endpoints: unavailable (HTTP 404), explicitly
  reported as `optional_unavailable` because the Worker is healthy.
- Side effects: no Telegram send, Railway write or configuration change.

The uploaded redacted artifact is the authoritative machine-readable record.
This evidence does not replace the pending signed delivery receipt canary.
