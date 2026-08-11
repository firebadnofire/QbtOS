# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "src/qbtos_control.py"
SPEC = importlib.util.spec_from_file_location("qbtos_control", MODULE_PATH)
control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(control)


class ServiceControlTests(unittest.TestCase):
    def test_clock_save_never_moves_persistent_floor_backwards(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = Path(directory) / "state/clock-epoch"
            clock.parent.mkdir()
            clock.write_text("200\n", encoding="ascii")
            with mock.patch.object(control, "CLOCK_EPOCH", clock), \
                    mock.patch.object(control.time, "time", return_value=100):
                control.clock_save()
            self.assertEqual(clock.read_text(encoding="ascii"), "200\n")

            with mock.patch.object(control, "CLOCK_EPOCH", clock), \
                    mock.patch.object(control.time, "time", return_value=300):
                control.clock_save()
            self.assertEqual(clock.read_text(encoding="ascii"), "300\n")

    def test_vpn_start_waits_for_dhcp_route(self):
        with mock.patch.object(
                control, "lan_ready", side_effect=[False, False, True]
                ) as ready, mock.patch.object(
                    control.time, "monotonic", side_effect=[0, 0, 1]
                ), mock.patch.object(control.time, "sleep") as sleep:
            self.assertTrue(control.wait_for_lan_ready(timeout=5))

        self.assertEqual(ready.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_vpn_start_dhcp_timeout_is_bounded(self):
        with mock.patch.object(control, "lan_ready", return_value=False), \
                mock.patch.object(control.time, "monotonic", side_effect=[0, 5]), \
                mock.patch.object(control.time, "sleep") as sleep:
            self.assertFalse(control.wait_for_lan_ready(timeout=5))

        sleep.assert_not_called()

    def test_vpn_start_waits_for_delayed_protection(self):
        with mock.patch.object(
                control, "vpn_check", side_effect=[False, False, True]
                ) as check, mock.patch.object(control, "run") as run, \
                mock.patch.object(control.time, "monotonic", side_effect=[0, 0, 1]), \
                mock.patch.object(control.time, "sleep") as sleep:
            self.assertTrue(control.wait_for_vpn_protection(timeout=5))

        self.assertEqual(check.call_count, 3)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(run.call_args.args[0][0], "/bin/ping")
        self.assertFalse(run.call_args.kwargs["check"])

    def test_vpn_start_timeout_remains_fail_closed(self):
        with mock.patch.object(control, "vpn_check", return_value=False), \
                mock.patch.object(control, "run") as run, \
                mock.patch.object(control.time, "monotonic", side_effect=[0, 5]):
            self.assertFalse(control.wait_for_vpn_protection(timeout=5))

        run.assert_not_called()

    def test_qbittorrent_start_refuses_unmounted_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "installed"
            config = root / "qBittorrent.conf"
            installed.write_text("installed\n", encoding="ascii")
            config.write_text("[Preferences]\n", encoding="ascii")
            with mock.patch.object(control, "INSTALLED", installed), \
                    mock.patch.object(control, "QBT_CONFIG", config), \
                    mock.patch.object(control, "vpn_check", return_value=True), \
                    mock.patch.object(
                        control, "persistent_data_status",
                        return_value=(False, "data is not mounted")), \
                    mock.patch.object(control, "qbt_stop") as stop:
                with self.assertRaisesRegex(RuntimeError, "data is not mounted"):
                    control.qbt_start()
            stop.assert_called_once_with()

    def test_status_explains_vpn_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "installed"
            config = root / "qBittorrent.conf"
            installed.write_text("installed\n", encoding="ascii")
            config.write_text("[Preferences]\n", encoding="ascii")
            with mock.patch.object(control, "INSTALLED", installed), \
                    mock.patch.object(control, "QBT_CONFIG", config), \
                    mock.patch.object(control, "QBT_PID", root / "missing.pid"), \
                    mock.patch.object(control, "vpn_check", return_value=False), \
                    mock.patch.object(
                        control, "persistent_data_status",
                        return_value=(True, "data is writable")), \
                    mock.patch("builtins.print") as output:
                control.status()
            payload = control.json.loads(output.call_args.args[0])
            self.assertEqual(payload["qbittorrent_state"], "blocked-vpn")
            self.assertTrue(payload["qbittorrent_configured"])

    def test_qbittorrent_stop_waits_for_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "qbittorrent.pid"
            pid_file.write_text("123\n", encoding="ascii")
            with mock.patch.object(control, "QBT_PID", pid_file), \
                    mock.patch.object(control, "run") as run, \
                    mock.patch.object(
                        control, "process_alive", side_effect=[True, True, False, False]
                    ), mock.patch.object(control.time, "sleep") as sleep:
                control.qbt_stop()

            self.assertEqual(run.call_count, 1)
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(pid_file.exists())

    def test_qbittorrent_stop_escalates_after_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "qbittorrent.pid"
            pid_file.write_text("123\n", encoding="ascii")
            with mock.patch.object(control, "QBT_PID", pid_file), \
                    mock.patch.object(control, "run") as run, \
                    mock.patch.object(control, "process_alive", return_value=True), \
                    mock.patch.object(
                        control.time, "monotonic", side_effect=[0, 11]
                    ):
                control.qbt_stop()

            self.assertEqual(run.call_count, 2)
            self.assertIn("KILL", run.call_args_list[-1].args[0])
            self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main()
