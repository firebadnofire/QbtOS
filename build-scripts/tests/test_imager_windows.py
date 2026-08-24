# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
IMAGER = REPO / "build-scripts" / "imager.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class WindowsImagerTests(unittest.TestCase):
    def test_tui_defaults_and_safety_are_explicit(self):
        source = IMAGER.read_text(encoding="utf-8")

        self.assertIn("Use Up/Down, Enter to select, or Esc to cancel.", source)
        self.assertIn("Type ERASE exactly to continue.", source)
        self.assertIn("$default = [string]$MaximumGiB", source)
        self.assertIn("QBTOS_DATA NTFS partition", source)
        self.assertIn("WindowsBuiltInRole]::Administrator", source)
        self.assertIn("if ($disk.IsBoot -or $disk.IsSystem)", source)
        self.assertIn("Set-Disk -Number $disk.Number -IsOffline $true", source)
        self.assertIn("Test-WrittenImage $resolvedImage $stream", source)
        self.assertIn("Enter a custom .img or .img.zst path", source)
        self.assertIn("Expand-ZstdImage $sourcePath $temporaryPath", source)
        self.assertIn("requires zstd.exe on PATH", source)
        self.assertIn("Remove-Item -LiteralPath $preparedImage.TemporaryPath", source)
        self.assertLess(
            source.index("Test-QbtOsImageLayout $resolvedImage"),
            source.index("(Get-CandidateDisks)"),
        )

    @unittest.skipUnless(POWERSHELL, "PowerShell is required")
    def test_help_does_not_require_elevation_or_an_image(self):
        result = subprocess.run(
            [POWERSHELL, "-NoLogo", "-NoProfile", "-File", str(IMAGER), "-Help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Usage: build-scripts\\imager.ps1", result.stdout)

    @unittest.skipUnless(POWERSHELL, "PowerShell is required")
    def test_gnu_style_image_parameter_is_accepted(self):
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(IMAGER),
                "--image",
                "not-opened-in-no-run-mode.img.zst",
                "-NoRun",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(POWERSHELL, "PowerShell is required")
    def test_adds_ntfs_logical_partition_without_replacing_base_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            disk = Path(temporary) / "disk.img"
            image_sectors = 8192
            data_sectors = 4096
            disk.write_bytes(b"\0" * ((image_sectors + 2048 + data_sectors) * 512))

            with disk.open("r+b") as stream:
                mbr = bytearray(512)
                struct.pack_into("<I", mbr, 440, 0x5142544F)
                partitions = (
                    (0x0C, 2048, 128),
                    (0x83, 2176, 128),
                    (0x83, 2304, 128),
                    (0x0F, 2432, image_sectors - 2432),
                )
                for index, (kind, start, size) in enumerate(partitions):
                    offset = 446 + index * 16
                    mbr[offset + 4] = kind
                    struct.pack_into("<II", mbr, offset + 8, start, size)
                mbr[510:512] = b"\x55\xaa"
                stream.write(mbr)

                ebr = bytearray(512)
                ebr[446 + 4] = 0x83
                struct.pack_into("<II", ebr, 446 + 8, 1, 1024)
                ebr[510:512] = b"\x55\xaa"
                stream.seek(2432 * 512)
                stream.write(ebr)

            command = (
                f". '{IMAGER}' -NoRun; "
                f"Test-QbtOsImageLayout '{disk}' | Out-Null; "
                f"$s=[IO.File]::Open('{disk}','Open','ReadWrite','None'); "
                f"try {{ "
                f"Add-QbtOsDataPartition $s {image_sectors * 512} "
                f"{data_sectors * 512} | Out-Null }} finally {{ $s.Dispose() }}"
            )
            subprocess.run(
                [POWERSHELL, "-NoLogo", "-NoProfile", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
            )

            with disk.open("rb") as stream:
                mbr = stream.read(512)
                original = [
                    struct.unpack_from("<4xB3xII", mbr, 446 + index * 16)
                    for index in range(4)
                ]
                stream.seek(2432 * 512)
                state_ebr = stream.read(512)
                stream.seek(image_sectors * 512)
                data_ebr = stream.read(512)

            self.assertEqual([entry[0] for entry in original[:3]], [0x0C, 0x83, 0x83])
            self.assertEqual(original[3][0:2], (0x0F, 2432))
            self.assertEqual(original[3][2], image_sectors + 2048 + data_sectors - 2432)
            self.assertEqual(state_ebr[446 + 16 + 4], 0x0F)
            self.assertEqual(
                struct.unpack_from("<II", state_ebr, 446 + 16 + 8),
                (image_sectors - 2432, 2048 + data_sectors),
            )
            self.assertEqual(data_ebr[446 + 4], 0x07)
            self.assertEqual(
                struct.unpack_from("<II", data_ebr, 446 + 8),
                (2048, data_sectors),
            )
            self.assertEqual(data_ebr[510:512], b"\x55\xaa")


if __name__ == "__main__":
    unittest.main()
