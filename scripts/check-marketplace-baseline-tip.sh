#!/usr/bin/env bash
# Print tip-of-upstream omacom/omarchy-plugin-marketplace SHA and blob SHAs
# for scripts/security-baseline*.mjs (drift watch). Does not run the scanner.
set -euo pipefail

REMOTE="${MARKETPLACE_REMOTE:-https://github.com/omacom/omarchy-plugin-marketplace.git}"
REF="${MARKETPLACE_REF:-main}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git init -q "$tmp"
git -C "$tmp" remote add origin "$REMOTE"
git -C "$tmp" fetch --depth 1 -q origin "$REF"
tip="$(git -C "$tmp" rev-parse FETCH_HEAD)"

printf 'tip %s\n' "$tip"
git -C "$tmp" ls-tree -r FETCH_HEAD -- scripts \
  | awk '$2 == "blob" && $4 ~ /^scripts\/security-baseline[^/]*\.mjs$/ {
      print "blob", $3, $4
    }'
