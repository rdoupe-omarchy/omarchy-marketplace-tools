"""Local marketplace baseline runner: metadata matches the bot schema."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run-marketplace-security-baseline.sh"
CHECK_TIP = ROOT / "scripts/check-marketplace-baseline-tip.sh"
FIXTURE = ROOT / "tests/fixtures/sample-plugin"
PLUGIN_SHA = "aab69655c08c9d0e0769be854bd44f58b4c59aac"

FAKE_BASELINE = """\
import {{ writeFileSync }} from "node:fs";
console.log("fake-baseline {marker}");
const json = process.argv.find((a) => a.startsWith("--json=")).slice("--json=".length);
writeFileSync(json, JSON.stringify({{ outcome: "passed" }}) + "\\n");
"""


def _git(repo, *args, check=True, **kwargs):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _init_git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _write_fake_marketplace(repo, marker):
    scripts = repo / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "security-baseline.mjs").write_text(FAKE_BASELINE.format(marker=marker))
    (scripts / "security-baseline-policy.mjs").write_text(f"// policy {marker}\n")
    _git(repo, "add", "scripts/security-baseline.mjs", "scripts/security-baseline-policy.mjs")
    _git(repo, "commit", "-m", marker)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _runner_env(remote, marketplace_dir=None, extra=None):
    env = {**os.environ, "MARKETPLACE_REMOTE": str(remote)}
    env.pop("MARKETPLACE_DIR", None)
    if marketplace_dir is not None:
        env["MARKETPLACE_DIR"] = str(marketplace_dir)
    if extra:
        env.update(extra)
    return env


class SecurityBaselineRunnerTests(unittest.TestCase):
    def test_help_exits_cleanly(self):
        result = subprocess.run(["bash", str(RUNNER), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--metadata-only", result.stdout)
        self.assertIn("marketplace-tip-sha", result.stdout)

    def test_metadata_only_matches_official_schema_and_root_manifest(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "bash", str(RUNNER),
                    "--local", str(FIXTURE),
                    "--repo", "https://github.com/example/sample-plugin",
                    "--sha", PLUGIN_SHA,
                    "--out", directory,
                    "--metadata-only",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            path = Path(result.stdout.strip())
            metadata = json.loads(path.read_text())
        self.assertEqual(metadata["schemaVersion"], 1)
        self.assertEqual(metadata["repoUrl"], "https://github.com/example/sample-plugin")
        self.assertEqual(metadata["repository"], "example/sample-plugin")
        self.assertEqual(metadata["commitSha"], PLUGIN_SHA)
        self.assertEqual(metadata["pluginIds"], [manifest["id"]])
        self.assertEqual(metadata["listedPlugins"], [{
            "pluginId": manifest["id"],
            "manifestPathHint": "manifest.json",
            "entryPoints": manifest["entryPoints"],
        }])
        self.assertEqual(metadata["entryPoints"], sorted(manifest["entryPoints"].values()))

    def test_missing_repo_or_sha_exits_invalid(self):
        result = subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--repo", result.stderr)

    def test_marketplace_dir_cache_is_reset_to_origin_main_every_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote"
            cache = root / "cache"
            out = root / "out"
            _init_git_repo(remote)
            v1 = _write_fake_marketplace(remote, "v1")
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", "main", str(remote), str(cache)],
                check=True,
                capture_output=True,
            )
            self.assertEqual(_git(cache, "rev-parse", "HEAD").stdout.strip(), v1)
            v2 = _write_fake_marketplace(remote, "v2")
            self.assertNotEqual(v1, v2)
            result = subprocess.run(
                [
                    "bash", str(RUNNER),
                    "--local", str(FIXTURE),
                    "--repo", "https://github.com/example/sample-plugin",
                    "--sha", PLUGIN_SHA,
                    "--out", str(out),
                ],
                capture_output=True,
                text=True,
                env=_runner_env(remote, cache),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_git(cache, "rev-parse", "HEAD").stdout.strip(), v2)
            self.assertEqual((out / "marketplace-tip-sha").read_text().strip(), v2)
            self.assertIn("fake-baseline v2", result.stdout)
            self.assertIn(f"marketplace-tip: {v2}", result.stdout)

    def test_explicit_marketplace_checkout_is_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote"
            pinned = root / "pinned"
            out = root / "out"
            _init_git_repo(remote)
            v1 = _write_fake_marketplace(remote, "v1")
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", "main", str(remote), str(pinned)],
                check=True,
                capture_output=True,
            )
            v2 = _write_fake_marketplace(remote, "v2")
            result = subprocess.run(
                [
                    "bash", str(RUNNER),
                    "--local", str(FIXTURE),
                    "--repo", "https://github.com/example/sample-plugin",
                    "--sha", PLUGIN_SHA,
                    "--out", str(out),
                    "--marketplace", str(pinned),
                ],
                capture_output=True,
                text=True,
                env=_runner_env(remote),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_git(pinned, "rev-parse", "HEAD").stdout.strip(), v1)
            self.assertNotEqual(_git(pinned, "rev-parse", "HEAD").stdout.strip(), v2)
            self.assertEqual((out / "marketplace-tip-sha").read_text().strip(), v1)
            self.assertIn("fake-baseline v1", result.stdout)

    def test_implicit_cache_rejects_existing_non_git_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote"
            cache = root / "cache"
            out = root / "out"
            _init_git_repo(remote)
            _write_fake_marketplace(remote, "v1")
            cache.mkdir()
            marker = cache / "do-not-delete.txt"
            marker.write_text("keep me\n")
            result = subprocess.run(
                [
                    "bash", str(RUNNER),
                    "--local", str(FIXTURE),
                    "--repo", "https://github.com/example/sample-plugin",
                    "--sha", PLUGIN_SHA,
                    "--out", str(out),
                ],
                capture_output=True,
                text=True,
                env=_runner_env(remote, cache),
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("not a git checkout", result.stderr)
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text(), "keep me\n")
            self.assertFalse((cache / ".git").exists())

    def test_implicit_cache_clones_when_path_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote"
            cache = root / "cache"
            out = root / "out"
            _init_git_repo(remote)
            tip = _write_fake_marketplace(remote, "fresh")
            result = subprocess.run(
                [
                    "bash", str(RUNNER),
                    "--local", str(FIXTURE),
                    "--repo", "https://github.com/example/sample-plugin",
                    "--sha", PLUGIN_SHA,
                    "--out", str(out),
                ],
                capture_output=True,
                text=True,
                env=_runner_env(remote, cache),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((cache / ".git").is_dir())
            self.assertEqual(_git(cache, "rev-parse", "HEAD").stdout.strip(), tip)
            self.assertEqual((out / "marketplace-tip-sha").read_text().strip(), tip)
            self.assertIn("fake-baseline fresh", result.stdout)


class MarketplaceBaselineTipTests(unittest.TestCase):
    def test_check_tip_prints_commit_and_blob_shas(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "remote"
            _init_git_repo(remote)
            tip = _write_fake_marketplace(remote, "watch")
            blob_baseline = _git(remote, "rev-parse", "HEAD:scripts/security-baseline.mjs").stdout.strip()
            blob_policy = _git(remote, "rev-parse", "HEAD:scripts/security-baseline-policy.mjs").stdout.strip()
            result = subprocess.run(
                ["bash", str(CHECK_TIP)],
                capture_output=True,
                text=True,
                env=_runner_env(remote),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"tip {tip}", result.stdout)
            self.assertIn(f"blob {blob_baseline} scripts/security-baseline.mjs", result.stdout)
            self.assertIn(f"blob {blob_policy} scripts/security-baseline-policy.mjs", result.stdout)

    def test_check_tip_fails_when_required_baseline_script_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "remote"
            _init_git_repo(remote)
            scripts = remote / "scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "security-baseline.mjs").write_text("// missing policy sibling\n")
            _git(remote, "add", "scripts/security-baseline.mjs")
            _git(remote, "commit", "-m", "incomplete baseline")
            result = subprocess.run(
                ["bash", str(CHECK_TIP)],
                capture_output=True,
                text=True,
                env=_runner_env(remote),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("scripts/security-baseline-policy.mjs", result.stderr)
