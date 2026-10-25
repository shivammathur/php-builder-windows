"""Run with python3 -m unittest discover -s scripts/tests (requires Bash 4+)."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MOCK = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["MOCK_CALLS"], "a") as log:
    log.write(json.dumps([Path(sys.argv[0]).name] + args) + "\\n")
if os.environ.get("MOCK_FAIL"):
    sys.exit(1)
data = json.loads(Path(os.environ["MOCK_DATA"]).read_text())
if Path(sys.argv[0]).name == "cloudsmith":
    if args[0] == "list":
        assert "--page-all" in args
        print(json.dumps({"data": data}))
else:
    if "DELETE" in args:
        sys.exit(0)
    if any("/releases/tags/" in arg for arg in args):
        print(42)
    else:
        page = int(next(arg for arg in args if "page=" in arg).split("&page=")[1])
        for item in data[(page-1)*100:page*100]:
            print(item["slug_perm"] + "\\t" + item["filename"])
'''


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        for command in ["gh", "cloudsmith"]:
            path = self.work / command
            path.write_text(MOCK)
            path.chmod(0o755)
        self.data = self.work / "data.json"
        self.data.write_text("[]")
        self.calls = self.work / "calls.jsonl"
        self.output = self.work / "cleanup.tsv"
        self.env = dict(os.environ, PATH=f"{self.work}:{os.environ['PATH']}",
                        MOCK_CALLS=str(self.calls), MOCK_DATA=str(self.data),
                        GITHUB_REPOSITORY="shivammathur/php-builder-windows",
                        GITHUB_RELEASES="php8.5", GITHUB_STEP_SUMMARY=str(self.work / "summary.md"))

    def packages(self, names):
        self.data.write_text(json.dumps([
            {"slug_perm": f"id{i}", "filename": name, "format": "raw"}
            for i, name in enumerate(names)
        ]))

    def run_script(self, script, source="cloudsmith", success=True):
        result = subprocess.run(["bash", str(ROOT / "scripts" / script), str(self.output), source],
                                cwd=ROOT, env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def rows(self):
        return [line.split("\t") for line in self.output.read_text().splitlines()]

    def test_retention_matches_github_including_sidecars_and_all_configurations(self):
        names = []
        for version in ["8.5.9", "8.5.10", "8.5.11-dev", "8.5.12-dev"]:
            for prefix in ["php", "php-devel-pack", "php-test-pack", "php-debug-pack"]:
                for suffix in [".zip", ".zip.cdx.json", ".zip.spdx.json", ".zip.openvex.json"]:
                    names.append(f"{prefix}-{version}-nts-Win32-vs17-x64{suffix}")
        names += ["Get-Php.ps1", "manifest.json", "php-master.zip", "php-8.5.1.log"]
        self.packages(names)
        self.run_script("release_cleanup_preview.sh", "github")
        github = self.rows()
        self.run_script("release_cleanup_preview.sh")
        self.assertEqual(self.rows(), github)
        self.assertEqual(len(github), 32)
        self.assertEqual({row[4] for row in github}, {"8.5.9", "8.5.11-dev"})
        self.assertIn("(cloudsmith)", (self.work / "summary.md").read_text())

    def test_filters_series_format_and_unrelated_files(self):
        self.packages(["php-8.5.1.zip", "php-8.5.2.zip", "php-8.4.1.zip",
                       "php-18.5.1.zip", "tool-8.5.99.zip", "php-master.zip",
                       "php-8.5.100.zip", "php-8.5.1.json"])
        data = json.loads(self.data.read_text())
        data[6]["format"] = "deb"
        self.data.write_text(json.dumps(data))
        self.run_script("release_cleanup_preview.sh")
        self.assertEqual([row[2] for row in self.rows()], ["php-8.5.1.zip"])

    def test_empty_and_dev_only_inventories(self):
        self.run_script("release_cleanup_preview.sh")
        self.assertEqual(self.rows(), [])
        self.packages(["php-8.5.1-dev.zip", "php-8.5.2-dev.zip"])
        self.run_script("release_cleanup_preview.sh")
        self.assertEqual([row[4] for row in self.rows()], ["8.5.1-dev"])

    def test_github_pagination_and_cloudsmith_all_pages(self):
        self.packages([f"php-8.5.{i}.zip" for i in range(1, 105)])
        self.run_script("release_cleanup_preview.sh", "github")
        github = self.rows()
        self.run_script("release_cleanup_preview.sh")
        self.assertEqual(self.rows(), github)
        self.assertEqual(len(github), 103)
        self.assertNotIn("8.5.104", {row[4] for row in github})

    def test_listing_failures_and_invalid_sources_fail(self):
        self.env["MOCK_FAIL"] = "1"
        self.run_script("release_cleanup_preview.sh", success=False)
        self.assertEqual(self.rows(), [])
        for script in ["release_cleanup_preview.sh", "release_cleanup_apply.sh"]:
            self.run_script(script, "invalid", success=False)

    def test_apply_uses_only_reviewed_package_ids_and_propagates_failure(self):
        self.output.write_text("php8.5\tOldSlug123\tphp-8.5.1.zip\tstable\t8.5.1\n")
        self.run_script("release_cleanup_apply.sh")
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], ["cloudsmith", "delete", "--yes",
                                      "shivammathur/php-builder-windows/OldSlug123"])
        self.env["MOCK_FAIL"] = "1"
        self.run_script("release_cleanup_apply.sh", success=False)
        self.output.write_text("")
        self.run_script("release_cleanup_apply.sh")

    def test_both_workflows_schedule_cloudsmith_only_candidates(self):
        for name in ["cleanup.yml", "cache.yml"]:
            workflow = (ROOT / ".github" / "workflows" / name).read_text()
            script = re.search(r'id: set-cleanup-matrix\n        run: \|\n(.*?)(?=\n  cleanup-apply:)',
                               workflow, re.S)[1]
            script = "\n".join(line[10:] for line in script.splitlines())
            lists = self.work / "cleanup-lists"
            lists.mkdir(exist_ok=True)
            github = lists / "cleanup-assets-8.5.tsv"
            cloudsmith = lists / "cleanup-cloudsmith-8.5.tsv"
            for has_github, has_cloudsmith in [(False, False), (False, True), (True, False), (True, True)]:
                github.write_text("candidate" if has_github else "")
                cloudsmith.write_text("candidate" if has_cloudsmith else "")
                result = subprocess.run(["bash", "-eu", "-c", script], cwd=self.work, text=True,
                                        capture_output=True, env=dict(self.env, GITHUB_OUTPUT=str(self.work / "output")))
                self.assertEqual(result.returncode, 0, result.stderr)
                matrix = json.loads(result.stdout.strip().split("=", 1)[1])
                self.assertEqual(matrix, {"include": [{"php": "8.5"}] if has_github or has_cloudsmith else []})
            self.assertIn("environment: release-cleanup", workflow)


if __name__ == "__main__":
    unittest.main()
