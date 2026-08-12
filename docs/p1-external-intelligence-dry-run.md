# External Intelligence offline dry-run

`python -m src.external_intelligence_e2e` verifies the private Gmail boundary,
source parser, conservative external risk score and creator release lineage
without network access, secrets or Telegram delivery. A single discovery
source is expected to remain R2/pending. This is a deterministic pre-flight
test, not proof of live source availability.
