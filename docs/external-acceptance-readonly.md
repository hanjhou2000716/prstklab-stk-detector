# Read-only external acceptance evidence

`src.external_acceptance` captures a redacted snapshot of the public Railway
health endpoint and the Pages release manifest. It does not send Telegram,
write to Railway, alter configuration, or read any secret. The output keeps
these states separate:

- `PASS`: both endpoints are reachable, the manifest is `ready`, and monitored
  sources are either healthy, no-event, no-new-content, or not checked.
- `NEEDS_REVERIFY`: an endpoint is unavailable, a manifest is invalid, or a
  monitored source is failed/configuration-missing. This is not a successful
  production acceptance.

When a manifest is `ready`, the capture also downloads each manifest-declared
public artifact and verifies its SHA-256 against `artifact_hashes`. The audit
is fail-closed on missing paths, invalid hashes, unavailable files, or a
mismatch. Artifact bytes are hashed in memory and never written to the report
or retained by this read-only collector. For the primary market, research and
event JSON artifacts it also compares each artifact's `snapshot_id` with the
corresponding snapshot ID in the manifest; a lineage mismatch is fail-closed.

Run locally with public URLs only:

```text
uv run python -m src.external_acceptance \
  --railway-url https://<railway-host>/ \
  --public-url https://<pages-host>/ \
  --output external-acceptance.json
```

The manual `External acceptance (read-only)` workflow performs the same
capture and stores only the redacted JSON artifact. It intentionally has
`contents: read` permission and no Telegram or Railway secret. A real
single-recipient Telegram acceptance must still use
`production-acceptance-photo.yml` after this evidence and the release gate
are healthy.

The report deliberately includes configuration variable *names* (for example,
which Gmail watch setting is missing) but never values, raw email content,
recipient IDs, tokens, cookies or full upstream response bodies.

The post-refresh capture at
`docs/evidence/external-acceptance-2026-08-22T0810.json` confirms that the
new Pages release is ready and all seven public artifact hashes and snapshot
identities match. It remains `NEEDS_REVERIFY` for external-only blockers:
GDELT HTTP 429, a health callback HTTP 403, missing Gmail watch configuration,
and the pending Railway delivery-secret migration.
