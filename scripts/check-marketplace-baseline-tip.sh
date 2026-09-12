#!/usr/bin/env bash
# Print tip-of-upstream omacom/omarchy-plugin-marketplace SHA and blob SHAs
# for the required security-baseline scripts (drift watch). Exits nonzero if
# either path is missing. Does not run the scanner.
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
for path in scripts/security-baseline.mjs scripts/security-baseline-policy.mjs; do
  blob="$(git -C "$tmp" rev-parse "FETCH_HEAD:$path")"
  printf 'blob %s %s\n' "$blob" "$path"
done
