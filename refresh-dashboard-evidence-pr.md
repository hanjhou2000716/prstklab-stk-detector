## Purpose

Record the latest successful `refresh-dashboard` publication and its read-only
public release smoke verification in the production integration audit.

## Evidence

- Refresh and Pages deployment: run `31883869066` (success).
- Public release smoke: run `31883967681` (success).
- Published release: `release-18e44bd16889fb7e`.
- Market snapshot: `87b41002eb87405b`.
- Research/event/Creator snapshot lineage is recorded in
  `docs/integration-status.md`.
- The refresh was intentionally non-delivery; the existing single-recipient
  photo receipt is kept separate and is not relabelled for the new release.

## Verification

- `git diff --check`
- Public manifest returned `status=ready` and the expected snapshot IDs.
- Read-only public release smoke passed.

## Rollback

Revert this documentation-only commit. It does not change producers, release
artifacts, notification policy, or runtime configuration.
