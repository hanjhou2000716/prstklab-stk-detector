# REQ-ADD-007 — Railway poll configuration extraction

This slice moves environment parsing and bounds for the Jin10/GDELT poll loop
into `railway-monitor/poll_config.py`. The existing monitor remains the only
poll loop and still owns source calls, classification, persistence and alert
policy. Required secrets continue to come through the existing `configured`
boundary; the new module never logs or publishes their values.

## Verification

The standalone tests cover defaults, invalid-number fallback, lower/upper
bounds, cooldown preservation and feature flags. The app compatibility call
site is exercised by the existing Railway monitor regression suite.

## Rollback

Revert the extraction commit and restore the four environment reads in
`monitor_forever`; no release schema or delivery data is changed.
