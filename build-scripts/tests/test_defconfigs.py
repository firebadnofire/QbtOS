# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
CONFIGS = REPO / "br2-external/configs"


class DefconfigTests(unittest.TestCase):
    def test_all_targets_include_curl_command_line_client(self):
        defconfigs = sorted(CONFIGS.glob("qbtos_*_defconfig"))
        self.assertEqual(len(defconfigs), 3)
        for defconfig in defconfigs:
            with self.subTest(defconfig=defconfig.name):
                source = defconfig.read_text(encoding="utf-8")
                self.assertIn("BR2_PACKAGE_LIBCURL_CURL=y\n", source)


if __name__ == "__main__":
    unittest.main()
