#!/usr/bin/env bash
# Run the official Omarchy marketplace Automated Security Baseline
# (the same scripts/security-baseline.mjs GitHub Actions bots execute).
#
# This is a local wrapper. It does not edit marketplace issues and is not a
# security audit. See README.md.
#
# When --marketplace is omitted, the cached omacom/omarchy-plugin-marketplace
# checkout is always fetched and reset to origin/main before the scan.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run-marketplace-security-baseline.sh [options]

Options:
  --repo URL          Public GitHub repository root URL
  --sha SHA           Full 40-character commit SHA (or a git rev if --local)
  --plugin-id ID      Override plugin ID (default: root manifest.json "id")
  --out DIR           Write metadata, report, and JSON here
  --marketplace DIR   Existing checkout (used as-is; no fetch/reset)
  --local DIR         Read root manifest.json from this checkout
  --json-only         Print only the JSON outcome path on stdout
  --metadata-only     Write validation-metadata.json and exit 0
  -h, --help          Show this help

When --marketplace is omitted, MARKETPLACE_DIR (or the XDG cache) is always
git fetch + reset --hard origin/main (or cloned) so a stale shallow clone is
never reused. The marketplace tip SHA is written to DIR/marketplace-tip-sha.

Examples:
  scripts/run-marketplace-security-baseline.sh \
    --repo https://github.com/rdoupe-omarchy/omarchy-underpants \
    --sha aab69655c08c9d0e0769be854bd44f58b4c59aac

  scripts/run-marketplace-security-baseline.sh --local /path/to/plugin --sha HEAD
EOF
}

repo_url=""
commit_sha=""
plugin_id=""
out_dir=""
marketplace_dir="${MARKETPLACE_DIR:-}"
marketplace_explicit=0
local_dir=""
json_only=0
metadata_only=0
MARKETPLACE_REMOTE="${MARKETPLACE_REMOTE:-https://github.com/omacom/omarchy-plugin-marketplace.git}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo_url="${2:-}"; shift 2 ;;
    --sha) commit_sha="${2:-}"; shift 2 ;;
    --plugin-id) plugin_id="${2:-}"; shift 2 ;;
    --out) out_dir="${2:-}"; shift 2 ;;
    --marketplace) marketplace_dir="${2:-}"; marketplace_explicit=1; shift 2 ;;
    --local) local_dir="${2:-}"; shift 2 ;;
    --json-only) json_only=1; shift ;;
    --metadata-only) metadata_only=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$local_dir" ]]; then
  local_dir="$(cd "$local_dir" && pwd)"
  if [[ -z "$repo_url" && -d "$local_dir/.git" ]]; then
    repo_url="$(git -C "$local_dir" remote get-url origin 2>/dev/null || true)"
    repo_url="${repo_url%.git}"
    repo_url="${repo_url/#git@github.com:/https://github.com/}"
  fi
  if [[ -z "$commit_sha" && -d "$local_dir/.git" ]]; then
    commit_sha="$(git -C "$local_dir" rev-parse HEAD)"
  fi
fi

if [[ -z "$repo_url" || -z "$commit_sha" ]]; then
  echo "Both --repo and --sha are required (or infer them with --local)." >&2
  exit 2
fi

if [[ ! "$repo_url" =~ ^https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "Repository URL must be https://github.com/owner/name" >&2
  exit 2
fi

if [[ "$commit_sha" == HEAD || ${#commit_sha} -ne 40 ]]; then
  if [[ -n "$local_dir" && -d "$local_dir/.git" ]]; then
    commit_sha="$(git -C "$local_dir" rev-parse "$commit_sha")"
  fi
fi
if [[ ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "commitSha must be a full 40-character lowercase SHA." >&2
  exit 2
fi

repository="${repo_url#https://github.com/}"
if [[ -z "$out_dir" ]]; then
  out_dir="${TMPDIR:-/tmp}/omarchy-security-baseline/${repository//\//-}-${commit_sha:0:12}"
fi
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

if [[ -n "$local_dir" && -f "$local_dir/manifest.json" ]]; then
  manifest_path="$local_dir/manifest.json"
else
  manifest_path="$out_dir/manifest.json"
  curl -fsSL "https://raw.githubusercontent.com/${repository}/${commit_sha}/manifest.json" \
    -o "$manifest_path"
fi

eval "$(python3 - "$manifest_path" "$plugin_id" <<'PY'
import json, shlex, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
plugin_id = sys.argv[2] or manifest.get("id")
entry_points = manifest.get("entryPoints") or {}
if not plugin_id or not isinstance(entry_points, dict) or not entry_points:
    raise SystemExit("Root manifest.json must have id and object entryPoints")
print(f"plugin_id={shlex.quote(str(plugin_id))}")
print(f"entry_points_json={shlex.quote(json.dumps(entry_points, separators=(',', ':')))}")
PY
)"

# Official writeValidationMetadata fields (schemaVersion 1), plus entryPoints
# on each listedPlugins row so a local rerun matches both the bot JSON and the
# commit's root manifest.
python3 - "$out_dir/validation-metadata.json" "$repo_url" "$repository" "$commit_sha" "$plugin_id" "$entry_points_json" <<'PY'
import json, sys
from pathlib import Path
entry_points = json.loads(sys.argv[6])
metadata = {
    "schemaVersion": 1,
    "repoUrl": sys.argv[2],
    "repository": sys.argv[3],
    "commitSha": sys.argv[4],
    "pluginIds": [sys.argv[5]],
    "listedPlugins": [{
        "pluginId": sys.argv[5],
        "manifestPathHint": "manifest.json",
        "entryPoints": entry_points,
    }],
    "entryPoints": sorted(entry_points.values()),
}
Path(sys.argv[1]).write_text(json.dumps(metadata, indent=2) + "\n")
PY

if [[ "$metadata_only" -eq 1 ]]; then
  printf '%s\n' "$out_dir/validation-metadata.json"
  exit 0
fi

refresh_marketplace_cache() {
  local dir="$1"
  mkdir -p "$(dirname "$dir")"
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" remote set-url origin "$MARKETPLACE_REMOTE"
    git -C "$dir" fetch --depth 1 origin main
    git -C "$dir" reset --hard origin/main
  else
    rm -rf "$dir"
    git clone --depth 1 --branch main "$MARKETPLACE_REMOTE" "$dir"
  fi
}

if [[ "$marketplace_explicit" -eq 0 ]]; then
  marketplace_dir="${marketplace_dir:-${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-plugin-marketplace}"
  refresh_marketplace_cache "$marketplace_dir"
fi

if [[ ! -f "$marketplace_dir/scripts/security-baseline.mjs" ]]; then
  echo "Missing scripts/security-baseline.mjs in $marketplace_dir" >&2
  exit 2
fi

marketplace_tip=""
if [[ -d "$marketplace_dir/.git" ]]; then
  marketplace_tip="$(git -C "$marketplace_dir" rev-parse HEAD)"
  printf '%s\n' "$marketplace_tip" > "$out_dir/marketplace-tip-sha"
fi

report="$out_dir/security-baseline-report.md"
json="$out_dir/security-baseline.json"
set +e
(
  cd "$marketplace_dir"
  node scripts/security-baseline.mjs \
    --metadata="$out_dir/validation-metadata.json" \
    --json="$json"
) > "$report"
status=$?
set -e

if [[ "$json_only" -eq 1 ]]; then
  printf '%s\n' "$json"
else
  cat "$report"
  echo
  echo "metadata: $out_dir/validation-metadata.json"
  echo "report:   $report"
  echo "json:     $json"
  if [[ -n "$marketplace_tip" ]]; then
    echo "marketplace-tip: $marketplace_tip"
  fi
  echo "exit:     $status"
fi
exit "$status"
