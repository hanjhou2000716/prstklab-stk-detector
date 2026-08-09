# P1 raw observation binding

The market publisher records each normalized snapshot in the append-only raw
observation store when `RAW_OBSERVATION_ROOT` is configured. The public
`site/data/market.json` contains only safe metadata (`enabled`, `recorded`,
`observation_id`, or a bounded reason); raw payloads remain outside the public
artifact. Recording is best-effort and the public file is still written
atomically, while the metadata gives source-health and release audits a clear
signal that the archive is unavailable.
