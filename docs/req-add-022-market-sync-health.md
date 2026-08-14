# REQ-ADD-022 market-sync health envelope

## Scope

Keep the existing read-only market confirmation payload while adding an
explicit observation status. A valid snapshot with no material move remains
an available observation; configuration, transport and parser failures are
separate health states and never become market confirmation.

## States

- `available`: a JSON object was fetched from the configured public URL.
- `configuration_missing`: no market snapshot URL was configured.
- `http_error` / `rate_limited`: the public endpoint rejected the request.
- `invalid_payload`: the endpoint returned malformed JSON shape.
- `failed`: an unexpected reader failure was contained at the boundary.

The Railway health payload records `market_sync.status`, source URL, fetch
time, bounded record count and a type-only error label. The existing app
wrapper still returns the raw dictionary, so `_market_sync_details` and the
fail-closed alert gate preserve their previous behavior.

## Verification and rollback

`tests/test_railway_market_sync.py` covers configuration-missing, valid-empty
snapshot and invalid-payload states. Reverting this atomic change restores the
legacy raw reader; it does not loosen the market-sync confirmation gate.

Live Pages freshness and Railway runtime evidence remain external acceptance
gates and must not be inferred from the local suite.
