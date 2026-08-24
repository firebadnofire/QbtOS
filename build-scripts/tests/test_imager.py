# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
IMAGER = REPO / "build-scripts/imager.sh"
IMAGE = REPO / "output/images/sdcard.img"


def bash(expression):
    return subprocess.run(
        ["bash", "-c", f'source "{IMAGER}"; {expression}'],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


class ImagerTests(unittest.TestCase):
    def test_device_warning_tags(self):
        self.assertEqual(bash("device_tags 1000 0 usb 1"), " (external)")
        self.assertEqual(
            bash(f"device_tags {101 * 1024**3} 0 sata 0"),
            " (large device)",
        )
        self.assertEqual(
            bash(f"device_tags {101 * 1024**3} 0 usb 1"),
            " (external) (large device)",
        )

    def test_zero_size_and_destructive_confirmation_are_explicit(self):
        source = IMAGER.read_text(encoding="utf-8")

        self.assertIn("How much free space following the OS do you want?", source)
        self.assertIn("Enter 0 to use", source)
        self.assertIn("your own USB", source)
        self.assertIn("Choose the filesystem for QBTOS_DATA.", source)
        self.assertIn('ntfs "Windows compatible', source)
        self.assertIn('DESTROY ALL DATA?', source)
        self.assertIn('[[ "$type" == "disk" ]]', source)

    def test_custom_and_compressed_images_are_supported(self):
        source = IMAGER.read_text(encoding="utf-8")

        self.assertIn('select_image() {', source)
        self.assertIn('Enter a custom .img or .img.zst path', source)
        self.assertIn('--image PATH', source)
        self.assertIn('*.zst)', source)
        self.assertIn('require_command zstd', source)
        self.assertIn('zstd -q -d --stdout -- "$image_source_path"', source)
        self.assertIn('trap cleanup_staged_image EXIT', source)
        self.assertLess(
            source.index('validate_image_layout "$image_path"'),
            source.index('selected_device=$(select_device)'),
        )

    def test_partition_refresh_handles_automount_races(self):
        source = IMAGER.read_text(encoding="utf-8")

        refresh = source.split("refresh_partition_table() {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn('unmount_children "$device"', refresh)
        self.assertIn('for attempt in {1..5}', refresh)
        self.assertIn('partx --update "$device"', refresh)

        main = source.split("main() {", 1)[1]
        extend_call = main.index(
            'extend_for_data_partition "$selected_device" "$data_gib"'
        )
        first_refresh = main.index(
            'refresh_partition_table "$selected_device"'
        )
        self.assertGreater(first_refresh, extend_call)

    def test_cached_checksum_verifies_written_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "sdcard.img"
            device = directory / "device"
            payload = b"qbtOS image payload\n" * 128
            image.write_bytes(payload)
            device.write_bytes(payload + b"unallocated trailing space")
            checksum = subprocess.run(
                ["sha256sum", image.name],
                cwd=directory,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout
            cache = directory / "sdcard.img.sha256"
            cache.write_text(checksum, encoding="utf-8")
            timestamp = max(image.stat().st_mtime, cache.stat().st_mtime)
            os.utime(image, (timestamp, timestamp))
            os.utime(cache, (timestamp, timestamp))

            output = bash(
                f'verify_written_image "{device}" "{image}" {len(payload)}'
            )

        self.assertIn("Using cached SHA-256", output)

    def test_build_creates_sd_image_checksum_cache(self):
        source = (REPO / "build-scripts/build.sh").read_text(encoding="utf-8")
        self.assertIn("sha256sum sdcard.img > sdcard.img.sha256", source)

    def test_image_reserves_an_extended_partition_for_data(self):
        genimage = (
            REPO / "br2-external/board/qbtos/rpi4/genimage.cfg"
        ).read_text(encoding="utf-8")
        fw_env = (
            REPO
            / "br2-external/board/qbtos/rpi4/rootfs-overlay/etc/fw_env.config"
        ).read_text(encoding="utf-8")

        self.assertIn("extended-partition = 4", genimage)
        self.assertIn("align = 1M", genimage)
        self.assertIn("5142544f-05", fw_env)

    @unittest.skipUnless(IMAGE.exists() and shutil.which("sfdisk"),
                         "built SD image and sfdisk are required")
    def test_built_image_passes_imager_layout_validation(self):
        bash(f'validate_image_layout "{IMAGE}"')

    @unittest.skipUnless(IMAGE.exists() and shutil.which("sfdisk"),
                         "built SD image and sfdisk are required")
    def test_data_partition_is_appended_without_replacing_os_slots(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "device.img"
            subprocess.run(
                ["cp", "--sparse=always", str(IMAGE), str(image)], check=True
            )
            subprocess.run(["truncate", "-s", "3G", str(image)], check=True)
            image_sectors = IMAGE.stat().st_size // 512
            data_sectors = 1024**3 // 512
            bash(
                f'extend_partition_table "{image}" '
                f'{image_sectors} {data_sectors}'
            )
            table = subprocess.run(
                ["sfdisk", "-d", str(image)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout

        for number in range(1, 7):
            self.assertIn(f"device.img{number} :", table)
        self.assertIn("size=     2097152, type=83", table)

    @unittest.skipUnless(IMAGE.exists() and shutil.which("sfdisk"),
                         "built SD image and sfdisk are required")
    def test_ntfs_data_partition_uses_windows_partition_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "device.img"
            subprocess.run(
                ["cp", "--sparse=always", str(IMAGE), str(image)], check=True
            )
            subprocess.run(["truncate", "-s", "3G", str(image)], check=True)
            image_sectors = IMAGE.stat().st_size // 512
            data_sectors = 1024**3 // 512
            bash(
                f'extend_partition_table "{image}" '
                f'{image_sectors} {data_sectors} 512 7'
            )
            table = subprocess.run(
                ["sfdisk", "-d", str(image)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout

        self.assertIn("size=     2097152, type=7", table)

    def test_target_supports_labeled_ntfs_data(self):
        kernel = (
            REPO / "br2-external/board/qbtos/common/kernel.fragment"
        ).read_text(encoding="utf-8")
        busybox = (
            REPO / "br2-external/board/qbtos/common/busybox.fragment"
        ).read_text(encoding="utf-8")
        persistence = (
            REPO
            / "br2-external/board/qbtos/common/rootfs-overlay/etc/init.d"
            / "S30qbtos-persistence"
        ).read_text(encoding="utf-8")

        self.assertIn("CONFIG_NTFS3_FS=y", kernel)
        self.assertIn("CONFIG_FEATURE_VOLUMEID_NTFS=y", busybox)
        self.assertIn("mount -t ntfs3", persistence)
        self.assertIn("windows_names", persistence)


if __name__ == "__main__":
    unittest.main()
