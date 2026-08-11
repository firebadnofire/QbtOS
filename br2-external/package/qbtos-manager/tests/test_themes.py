# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "src/qbtos_themes.py"
SPEC = importlib.util.spec_from_file_location("qbtos_themes_test", MODULE_PATH)
themes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(themes)


def create_theme(path, marker="theme"):
    (path / "public").mkdir(parents=True)
    (path / "public/index.html").write_text(marker, encoding="utf-8")


class ThemeTests(unittest.TestCase):
    def test_git_https_transport_failure_is_actionable(self):
        failure = themes.subprocess.CalledProcessError(
            128, ["git", "clone"], stderr=(
                "git: 'remote-https' is not a git command. See 'git --help'.\n"
                "fatal: remote helper 'https' aborted session\n"))
        with mock.patch.object(themes.subprocess, "run", side_effect=failure):
            with self.assertRaisesRegex(
                    themes.ThemeError, "missing Git HTTPS transport support"):
                themes._run_git(["clone", "--", "https://example.org/theme.git"])

    def test_repository_must_be_public_credential_free_https(self):
        self.assertEqual(
            themes.validate_git_url("https://example.org/owner/theme.git"),
            "https://example.org/owner/theme.git")
        for value in (
                "http://example.org/theme.git", "git@example.org:theme.git",
                "https://user:secret@example.org/theme.git",
                "https://example.org/theme.git?token=secret"):
            with self.subTest(value=value), self.assertRaises(themes.ThemeError):
                themes.validate_git_url(value)

    def test_theme_name_rejects_path_traversal(self):
        for value in ("../theme", ".", "theme/name", "-option"):
            with self.subTest(value=value), self.assertRaises(themes.ThemeError):
                themes.validate_name(value)

    def test_theme_requires_public_index_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme"
            create_theme(path)
            self.assertEqual(themes.validate_theme(path), path)
            (path / "public/escape").symlink_to("/etc/passwd")
            with self.assertRaises(themes.ThemeError):
                themes.validate_theme(path)

    def test_install_and_update_use_atomic_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def clone_first(_url, destination, _branch=""):
                create_theme(destination, "first")

            with mock.patch.object(themes, "_clone", side_effect=clone_first):
                themes.install_theme(
                    "clean-ui", "https://example.org/clean-ui.git", root=root)
            self.assertEqual(
                (root / "clean-ui/public/index.html").read_text(encoding="utf-8"),
                "first")

            def clone_second(_url, destination, _branch=""):
                create_theme(destination, "second")

            with mock.patch.object(
                    themes, "_git_metadata",
                    return_value=("https://example.org/clean-ui.git", "main")), \
                    mock.patch.object(themes, "_clone", side_effect=clone_second):
                themes.update_theme("clean-ui", root=root)
            self.assertEqual(
                (root / "clean-ui/public/index.html").read_text(encoding="utf-8"),
                "second")
            self.assertEqual([path.name for path in root.iterdir()], ["clean-ui"])

    def test_qbittorrent_preferences_select_and_disable_theme(self):
        selected = themes.theme_preferences("[Preferences]\nValue=1\n", "clean-ui")
        self.assertIn("WebUI\\AlternativeUIEnabled=true", selected)
        self.assertIn("WebUI\\RootFolder=/themes/clean-ui", selected)
        self.assertEqual(themes.active_theme(selected), "clean-ui")
        disabled = themes.theme_preferences(selected, "")
        self.assertIn("WebUI\\AlternativeUIEnabled=false", disabled)
        self.assertEqual(themes.active_theme(disabled), "")


if __name__ == "__main__":
    unittest.main()
