# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
CONFIGS = REPO / "br2-external/configs"
KMOD_MAKEFILE = REPO / "buildroot/package/kmod/kmod.mk"


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

    def test_rpi4_kmod_can_load_xz_compressed_kernel_modules(self):
        source = (CONFIGS / "qbtos_rpi4_defconfig").read_text(encoding="utf-8")
        kmod_makefile = KMOD_MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("BR2_PACKAGE_KMOD_TOOLS=y\n", source)
        self.assertIn("BR2_PACKAGE_HOST_KMOD_XZ=y\n", source)
        self.assertIn("BR2_PACKAGE_XZ=y\n", source)
        self.assertIn("ifeq ($(BR2_PACKAGE_XZ),y)\n", kmod_makefile)
        self.assertIn("KMOD_CONF_OPTS += -Dxz=enabled\n", kmod_makefile)


if __name__ == "__main__":
    unittest.main()
