# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
POST_BUILD = REPO / "br2-external/board/qbtos/common/post-build.sh"


def find_shell():
    shell = shutil.which("sh")
    if shell or os.name != "nt":
        return shell
    git = shutil.which("git")
    if git:
        candidate = Path(git).parents[1] / "bin/sh.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def parse_os_release(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key] = value
    return values


class OsReleaseTests(unittest.TestCase):
    def run_hook(self, environment=None):
        shell = find_shell()
        if not shell:
            self.skipTest("POSIX shell is unavailable")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name)
        (target / "usr/lib").mkdir(parents=True)
        (target / "etc").mkdir()
        (target / "usr/lib/os-release").write_text(
            "NAME=Buildroot\nID=buildroot\n", encoding="utf-8"
        )
        if os.name != "nt":
            os.symlink("../usr/lib/os-release", target / "etc/os-release")

        hook_environment = os.environ.copy()
        hook_environment["TARGET_DIR"] = str(target)
        if environment:
            hook_environment.update(environment)
        subprocess.run(
            [shell, POST_BUILD, target, "--os-release-only"],
            env=hook_environment,
            check=True,
        )
        return target, parse_os_release(target / "usr/lib/os-release")

    def test_release_build_has_standard_and_qbtos_metadata(self):
        commit = "a" * 40
        target, values = self.run_hook(
            {
                "QBTOS_RELEASE_BUILD": "1",
                "QBTOS_VERSION": "2026-08-24-rev22",
                "QBTOS_BUILD_DATE": "2026-08-24",
                "QBTOS_REVISION": "22",
                "QBTOS_SOURCE_TAG": "revision-22",
                "QBTOS_COMMIT": commit,
            }
        )

        if os.name != "nt":
            self.assertTrue((target / "etc/os-release").is_symlink())
            self.assertEqual(
                os.readlink(target / "etc/os-release"), "../usr/lib/os-release"
            )
        self.assertEqual(values["NAME"], "qbtOS")
        self.assertEqual(values["ID"], "qbtos")
        self.assertEqual(values["ID_LIKE"], "buildroot")
        self.assertEqual(values["VERSION_ID"], "2026-08-24-rev22")
        self.assertEqual(values["PRETTY_NAME"], "qbtOS 2026-08-24-rev22")
        self.assertEqual(values["BUILD_ID"], commit)
        self.assertEqual(values["IMAGE_ID"], "qbtos")
        self.assertEqual(values["IMAGE_VERSION"], "2026-08-24-rev22")
        self.assertEqual(values["QBTOS_BUILD_DATE"], "2026-08-24")
        self.assertEqual(values["QBTOS_REVISION"], "22")
        self.assertEqual(values["QBTOS_SOURCE_TAG"], "revision-22")
        self.assertEqual(values["QBTOS_COMMIT"], commit)
        self.assertEqual(values["QBTOS_CHANNEL"], "stable")
        self.assertEqual(
            values["HOME_URL"], "https://pubcode.archuser.org/firebadnofire/qbtOS"
        )

    def test_development_build_is_identified_without_release_environment(self):
        _, values = self.run_hook()

        self.assertEqual(values["VERSION_ID"], "development")
        self.assertEqual(values["PRETTY_NAME"], "qbtOS development")
        self.assertEqual(values["QBTOS_BUILD_DATE"], "unknown")
        self.assertEqual(values["QBTOS_REVISION"], "0")
        self.assertEqual(values["QBTOS_SOURCE_TAG"], "unreleased")
        self.assertEqual(values["QBTOS_COMMIT"], "unknown")


if __name__ == "__main__":
    unittest.main()
