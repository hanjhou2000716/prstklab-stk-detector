# Offline end-to-end test plan

`python -m src.system_dry_run` exercises source/event normalization, lifecycle,
budget, release provenance, intelligence evidence, and Mini App routing without
network access or formal Telegram recipients. Production delivery remains
behind the release gate; mocked `sendPhoto` tests cover the Telegram boundary.
## Full offline delivery gate

`python -m src.full_offline_e2e` composes the release dry-run, fixed-size
renderer, Mini App deep link and mocked Telegram `sendPhoto` path. It verifies
that the first recipient uploads the public card and the second recipient
reuses the returned Telegram `file_id`. The harness uses CI-only recipient
labels and a mocked HTTP client; it never contacts Telegram or uses a
production token.
