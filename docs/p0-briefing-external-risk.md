# P0 Briefing external-risk binding

`build_briefing_snapshot` now forwards a sanitized `external_observations`
array into the shared intelligence pipeline. FinancialJuice/Jin10/GDELT
observations therefore use the same cluster and R0–R4 policy as other event
paths; creator/editorial content remains non-evidence. A single discovery
observation stays pending with an explicit reason and cannot become a
high-risk notification.

The field is optional for backward compatibility. Missing or malformed input
is treated as an empty observation set, not as proof that no external event
exists.
