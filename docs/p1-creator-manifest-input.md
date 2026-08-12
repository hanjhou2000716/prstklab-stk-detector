# P1 Creator records at manifest build

The release builder now accepts an optional `--creator-records` JSON file. It
must contain a JSON array of already-sanitized public Creator Insight records
(or an object with a `records` array). The builder then:

1. computes the market/research/event parent release ID;
2. runs the Creator Intelligence privacy and source policy again;
3. creates `creator-release.json` bound to that exact release and snapshots;
4. includes its path and SHA-256 in the manifest.

Raw email bodies, attachments, local paths and private URLs are rejected by
the pipeline and are never written to `site/data`. If the input is absent, the
core release remains unchanged and the creator artifact is optional. If the
file is malformed, the build fails rather than publishing an ambiguous release.

Example:

```powershell
python -m src.release_manifest --creator-records data/creator-records.json
```

The input file should be kept outside the public Pages tree and removed after
the build when it is generated from a private ingress job.
