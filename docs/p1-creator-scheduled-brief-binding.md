# Creator records in scheduled briefs

`scheduled_delivery.prepare` optionally reads `CREATOR_RECORDS_PATH` when the
path points to a checked-out, sanitized JSON file outside `site/`.  Valid
records are attached to the exact market snapshot before the briefing is built;
the release-manifest step consumes the same input to create the immutable
creator artifact.  Missing, malformed, or public-tree paths are ignored and do
not make a release appear complete or introduce private media into Pages.

The variable is optional.  A producer should provide only normalized public
fields accepted by `creator-intelligence`; raw email bodies, local paths,
attachments, credentials, and private URLs are rejected by the downstream
creator release validator.
