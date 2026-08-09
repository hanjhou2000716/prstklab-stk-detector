# P1 research instrument identity

Research candidates now pass through `InstrumentMaster` during CSV
normalization. Known symbols carry the canonical `instrument_id`, asset type,
currency and timezone. A symbol outside the compact registry is retained with
`instrument_resolution=unknown` and null identity fields; the scanner never
guesses a cross-market mapping. This keeps research cards explainable while
allowing the full public universe to remain larger than the registry.
