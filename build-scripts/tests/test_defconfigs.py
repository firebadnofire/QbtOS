# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
CONFIGS = REPO / "br2-external/configs"


class DefconfigTests(unittest.TestCase):
    def setUp(self):
        self.defconfigs = sorted(CONFIGS.glob("qbtos_*_defconfig"))
        self.assertEqual(len(self.defconfigs), 3)

    def test_all_targets_include_curl_command_line_client(self):
        for defconfig in self.defconfigs:
            with self.subTest(defconfig=defconfig.name):
                source = defconfig.read_text(encoding="utf-8")
                self.assertIn("BR2_PACKAGE_LIBCURL_CURL=y\n", source)

    def test_all_targets_replace_buildroot_os_release_after_finalization(self):
        script = (
            'BR2_ROOTFS_POST_FAKEROOT_SCRIPT="$(BR2_EXTERNAL_QBTOS_PATH)'
            '/board/qbtos/common/post-build.sh"\n'
        )
        arguments = 'BR2_ROOTFS_POST_FAKEROOT_SCRIPT_ARGS="--os-release-only"\n'
        for defconfig in self.defconfigs:
            with self.subTest(defconfig=defconfig.name):
                source = defconfig.read_text(encoding="utf-8")
                self.assertIn(script, source)
                self.assertIn(arguments, source)


if __name__ == "__main__":
    unittest.main()
