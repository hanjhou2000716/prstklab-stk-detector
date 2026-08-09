# Offline end-to-end test plan

`python -m src.system_dry_run` exercises source/event normalization, lifecycle,
budget, release provenance, intelligence evidence, and Mini App routing without
network access or formal Telegram recipients. Production delivery remains
behind the release gate; mocked `sendMessage` tests cover the scheduled
Telegram boundary, while mocked `sendPhoto` tests cover only the scoped photo
smoke workflow.
