#!/usr/bin/env bash
set -euo pipefail
target="${TMPDIR:-/tmp}/sc2129-fixture"
echo first >> "$target"
echo second >> "$target"
