# Public release smoke gate

The public smoke workflow validates the exact immutable release served by
GitHub Pages. A checkout of `main` contains only placeholder `site/data`
files, so the workflow first restores `origin/data-release` into the local
workspace. It then compares the local release identity and hashes with the
public manifest and artifacts.

This is a no-delivery check: it has no Telegram token, no notification step,
and cannot send a message. A mismatch fails closed and leaves the existing
Pages release untouched.

## Run

Dispatch `.github/workflows/public-release-smoke.yml` with:

- `public_url`: the Pages base URL;
- `expected_snapshot_id`: optional market snapshot ID recorded by the
  publisher.

The workflow must remain read-only (`contents: read`) and must not be changed
to publish data or send notifications.
