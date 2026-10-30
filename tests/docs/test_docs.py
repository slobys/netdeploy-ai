"""Offline safety, navigation, and publishing checks for the public handbook."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DOCS = PROJECT / "docs" / "site"
SCRIPT = PROJECT / "scripts" / "gcp-root-setup.sh"
spec = importlib.util.spec_from_file_location("netdeploy_docs_build", DOCS / "build.py")
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = builder.build(Path(cls.temp.name) / "public")
        cls.config = json.loads((DOCS / "site.json").read_text(encoding="utf-8"))
        cls.pages = [p for g in cls.config["groups"] for p in g["pages"]]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_nine_chinese_pages_and_sidebar(self):
        self.assertEqual(len(self.pages), 9)
        for page in self.pages:
            source = (self.output / (page["id"] + ".html")).read_text(encoding="utf-8")
            self.assertIn('lang="zh-CN"', source)
            self.assertIn('id="sidebar"', source)
            self.assertIn(page["description"], source)
            self.assertIn("NetDeploy AI", source)

    def test_complete_navigation_and_search_targets(self):
        records = json.loads((self.output / "search-index.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(records), 55)
        self.assertTrue(any("root" in entry["text"].lower() for entry in records))
        self.assertTrue(any("防火墙" in entry["text"] for entry in records))
        builder.validate(self.output)
        self.assertIn("https://slobys.github.io/netdeploy-ai/",
                      (self.output / "index.html").read_text(encoding="utf-8"))

    def test_reject_broken_or_unsafe_links(self):
        file = self.output / "index.html"
        original = file.read_text(encoding="utf-8")
        try:
            file.write_text(original.replace("</article>", '<a href="missing.html">x</a></article>'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "broken link"):
                builder.validate(self.output)
        finally:
            file.write_text(original, encoding="utf-8")

    def test_only_public_artifacts_are_emitted(self):
        names = {x.name for x in self.output.iterdir()}
        expected = {p["id"] + ".html" for p in self.pages} | {
            "404.html", "site.css", "site.js", "search-index.json", "robots.txt",
            "sitemap.xml", ".nojekyll"
        }
        self.assertEqual(names, expected)
        self.assertFalse(names & {".env", "known_hosts", "secrets", "data", "app", ".git"})

    def test_gcp_script_defaults_to_interactive_password_only(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('mode="--password-only"', source)
        self.assertIn("passwd root", source)
        self.assertIn("--enable-root-password-ssh", source)
        self.assertIn("ENABLE ROOT PASSWORD SSH", source)
        self.assertIn("sshd_bin", source)
        self.assertIn('"$sshd_bin" -t', source)
        self.assertIn('"$sshd_bin" -T', source)
        self.assertIn("rollback()", source)
        self.assertIn("Metadata-Flavor: Google", source)
        self.assertNotIn("chpasswd", source)
        self.assertNotRegex(source, r"(?m)^\s*(sudo\s+)?reboot\b")
        self.assertNotRegex(source, r"echo\s+root:[^\s|]+")

    # Windows may resolve 'bash' to an unconfigured WSL stub instead of Git Bash;
    # the same script is syntax checked on Ubuntu CI and in docs workflow.
    @unittest.skipIf(sys.platform == "win32" or shutil.which("bash") is None,
                     "GCP Bash syntax and help checks require a real POSIX Bash")
    def test_gcp_script_syntax_and_help_do_not_require_root(self):
        check = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        help_result = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--password-only", help_result.stdout)

    def test_version_and_app_help_link(self):
        source = (PROJECT / "app" / "main.py").read_text(encoding="utf-8")
        match = re.search(r'FastAPI\(title="NetDeploy AI", version="([^"]+)"\)', source)
        self.assertIsNotNone(match)
        self.assertEqual(self.config["version"], match.group(1))
        panel = (PROJECT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('https://slobys.github.io/netdeploy-ai/', panel)


if __name__ == "__main__":
    unittest.main()
