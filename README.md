# omarchy-marketplace-tools

Ops wrappers for the official Omarchy plugin marketplace. **This is not a plugin**
and must not be submitted to the marketplace.

The first tool replays the Automated Security Baseline that GitHub Actions bots
run from
[omacom/omarchy-plugin-marketplace](https://github.com/omacom/omarchy-plugin-marketplace)
`scripts/security-baseline.mjs` after validation writes `validation-metadata.json`.

It is a static exact-commit check, not a security audit. It does not execute
plugin code. Official workflows use Node 24.

This tree was relocated out of
[rdoupe-omarchy/omarchy-underpants#2](https://github.com/rdoupe-omarchy/omarchy-underpants/pull/2)
so Underpants `main` can stay frozen at `aab69655` for marketplace #6213.

## Create this GitHub repo (required)

This agent could not create `rdoupe-omarchy/omarchy-marketplace-tools` (GitHub
API 403). From a machine with org `repo` create permission:

```bash
gh repo create rdoupe-omarchy/omarchy-marketplace-tools \
  --public \
  --description "Local runner for the official Omarchy marketplace Automated Security Baseline (ops, not a plugin)"
```

Then publish this orphan tree (currently parked on Underpants so the files are
fetchable, **not** as a merge to Underpants `main`):

```bash
git clone --branch cursor/omarchy-marketplace-tools-706c \
  https://github.com/rdoupe-omarchy/omarchy-underpants.git \
  omarchy-marketplace-tools
cd omarchy-marketplace-tools
git remote set-url origin https://github.com/rdoupe-omarchy/omarchy-marketplace-tools.git
git push -u origin cursor/omarchy-marketplace-tools-706c:main
```

Alternatively apply `omarchy-marketplace-tools.patch` onto a fresh empty repo
and push.

## Wrapper

```bash
bash scripts/run-marketplace-security-baseline.sh \
  --repo https://github.com/rdoupe-omarchy/omarchy-underpants \
  --sha aab69655c08c9d0e0769be854bd44f58b4c59aac
```

From a plugin checkout (infers `origin` + `HEAD` unless overridden):

```bash
bash scripts/run-marketplace-security-baseline.sh --local /path/to/plugin
```

When `--marketplace` is omitted, the runner always `git fetch` +
`git reset --hard origin/main` against
[omacom/omarchy-plugin-marketplace](https://github.com/omacom/omarchy-plugin-marketplace)
(or clones it) before invoking `node scripts/security-baseline.mjs`. A cached
shallow clone in `MARKETPLACE_DIR` or `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-plugin-marketplace`
is never reused stale. If that implicit cache path already exists and is not a
git checkout, the runner exits nonzero and does not delete it. The marketplace
tip SHA is written to `$OUT/marketplace-tip-sha`.

`--marketplace DIR` uses that checkout as-is (no fetch) for pinning or tests.

To print the current upstream tip and blob SHAs for `security-baseline*.mjs`
(drift watch):

```bash
bash scripts/check-marketplace-baseline-tip.sh
```

## Exact bot command

```bash
git clone --depth 1 https://github.com/omacom/omarchy-plugin-marketplace.git \
  /tmp/omarchy-plugin-marketplace

# Official writeValidationMetadata fields (schemaVersion 1), plus
# listedPlugins.entryPoints from that commit's root manifest.json.
# The scanner requires listedPlugins[].pluginId and listedPlugins[].manifestPathHint.
cat > /tmp/validation-metadata.json <<'EOF'
{
  "schemaVersion": 1,
  "repoUrl": "https://github.com/rdoupe-omarchy/omarchy-underpants",
  "commitSha": "aab69655c08c9d0e0769be854bd44f58b4c59aac",
  "pluginIds": ["douper.underpants"],
  "listedPlugins": [
    {
      "pluginId": "douper.underpants",
      "manifestPathHint": "manifest.json",
      "entryPoints": { "overlay": "Launcher.qml" }
    }
  ],
  "entryPoints": ["Launcher.qml"]
}
EOF

node /tmp/omarchy-plugin-marketplace/scripts/security-baseline.mjs \
  --metadata=/tmp/validation-metadata.json \
  --json=/tmp/security-baseline.json
```

Stdout is the markdown report bots post. `--json` is the machine-readable
`outcome`, `findings`, `capabilities`, and `verifiedPublicationDisposition`.

Exit `0` means a complete result (`passed`, `review-required`, or
`needs-fixes`). Exit `3` is a scan-limit failure. Exit `2` is an invalid or
unavailable scan.

## Tests

```bash
python3 -m unittest discover -s tests
```

## What this catch set is (and is not)

This wrapper catches **only** the public V3 selective Automated Security Baseline:
the findings and review capabilities documented in
[omacom/omarchy-plugin-marketplace `SECURITY.md`](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md#automated-security-baseline).

Findings (only these):

- `curl-pipe-shell`
- `cargo-git-unpinned`
- `remote-git-execution-unpinned`
- `sudoers-dangerous-passwordless-command`
- `privileged-process-control-from-shared-temp`

Capabilities (review, not findings): `installer`, `package-manager`,
`privilege`, `remote-build`, `bundled-executable-binary`,
`service-management`, `sudoers-modification`.

It does **not** replace HANCORE-linux (or other maintainer) manual review
comments. Those cover issues the public scanner does not encode as findings,
including TOCTOU / missing `O_NOFOLLOW`, ambient `PATH`, `StdioCollector`
capability gaps, generic `open("w")` + `flock` races, AGENTS.md prompt
injection, and other review-only notes.

### Pre-push gate

Run this wrapper on the **exact commit** about to be frozen or pushed. A later
`HEAD` is a different snapshot. Marketplace bots bind the baseline to a full
40-character SHA; a changed branch head invalidates the recorded result.

```bash
git rev-parse HEAD   # confirm this is the commit you will push
bash scripts/run-marketplace-security-baseline.sh --local /path/to/plugin --sha HEAD
```
