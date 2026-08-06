# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
BOARD = REPO / "br2-external/board/qbtos/rpi4"


def environment():
    values = {}
    for line in (BOARD / "uboot-env.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


class RaspberryPiBootTests(unittest.TestCase):
    def test_kernel_does_not_overwrite_running_boot_script(self):
        values = environment()
        kernel_address = int(values["kernel_addr_r"], 0)
        script_address = int(values["scriptaddr"], 0)

        # U-Boot's Raspberry Pi environment reserves through 0x02400000 for
        # an uncompressed kernel and puts scripts in the 0x05400000 region.
        self.assertEqual(kernel_address, 0x00080000)
        self.assertEqual(script_address, 0x05400000)
        self.assertGreaterEqual(script_address, 0x02400000)

    def test_headless_uboot_console_is_routed_to_uart(self):
        values = environment()

        self.assertEqual(values["stdin"], "serial")
        self.assertEqual(values["stdout"], "serial")
        self.assertEqual(values["stderr"], "serial")

    def test_kernel_failure_stops_at_recovery_prompt(self):
        boot_script = (BOARD / "boot.cmd").read_text(encoding="utf-8")

        failure = boot_script.split(
            'echo "qbtOS: selected slot failed before entering Linux"', 1)[1]
        self.assertNotIn("\nreset\n", failure)
        self.assertIn("automatic reset suppressed", failure)

    def test_uart_is_enabled_during_firmware_and_later_stages(self):
        config = (BOARD / "config.txt").read_text(encoding="utf-8")
        command_line = (BOARD / "cmdline.txt").read_text(encoding="utf-8")
        boot_script = (BOARD / "boot.cmd").read_text(encoding="utf-8")

        self.assertIn("enable_uart=1", config)
        self.assertIn("uart_2ndstage=1", config)
        self.assertIn("init_uart_clock=48000000", config)
        self.assertIn("enable_gic=1", config)
        self.assertIn("dtoverlay=disable-bt", config)
        self.assertIn("console=ttyAMA0,115200n8", command_line)
        self.assertIn("console=ttyAMA0,115200n8", boot_script)

    def test_uboot_fatal_errors_remain_visible_on_uart(self):
        fragment = (BOARD / "uboot.fragment").read_text(encoding="utf-8")
        trace_patch = (
            BOARD / "patches/uboot/0001-initcall-trace-early-uart.patch"
        ).read_text(encoding="utf-8")

        self.assertIn("CONFIG_PANIC_HANG=y", fragment)
        self.assertIn("CONFIG_DEBUG_UART=y", fragment)
        self.assertIn("CONFIG_DEBUG_UART_PL011=y", fragment)
        self.assertIn("CONFIG_DEBUG_UART_BASE=0xfe201000", fragment)
        self.assertIn("CONFIG_DEBUG_UART_CLOCK=48000000", fragment)
        self.assertIn("CONFIG_DEBUG_UART_ANNOUNCE=y", fragment)
        self.assertIn("CONFIG_EFI_LOADER=n", fragment)
        self.assertIn('printascii("[init] " #_call', trace_patch)
        self.assertIn("GD_FLG_HAVE_CONSOLE", trace_patch)

    def test_unbound_console_node_falls_back_without_dereference(self):
        console_patch = (
            BOARD / "patches/uboot/0002-serial-check-bound-console.patch"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "*devp && device_get_uclass_id(*devp) == UCLASS_SERIAL",
            console_patch,
        )

    def test_mdev_system_materializes_mbr_partuuid_links(self):
        persistence = (
            REPO
            / "br2-external/board/qbtos/common/rootfs-overlay/etc/init.d"
            / "S30qbtos-persistence"
        ).read_text(encoding="utf-8")

        self.assertIn("link_qbtos_mbr_partitions", persistence)
        self.assertIn('skip=440 count=4', persistence)
        self.assertIn('disk_signature="$4$3$2$1"', persistence)
        self.assertIn('/dev/disk/by-partuuid/${disk_signature}-0', persistence)


if __name__ == "__main__":
    unittest.main()
