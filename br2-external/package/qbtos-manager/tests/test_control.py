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
    def test_firewall_exposes_shares_only_to_trusted_lan(self):
        firewall = (
            Path(__file__).parents[3]
            / "board/qbtos/common/rootfs-overlay/etc/nftables-qbtos.conf"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'iifname "eth0" ip saddr @trusted_ipv4 tcp dport { 445, 2049 } accept',
            firewall)
        self.assertIn(
            'iifname { "wg0", "tun0" } tcp dport { 445, 2049, 8080, 8081 } drop',
            firewall)

    def test_smb_config_is_guest_lan_only_and_exports_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "samba"
            config = Path(directory) / "smb.conf"
            downloads = Path(directory) / "downloads"
            downloads.mkdir()
            with mock.patch.object(control, "SMB_RUNTIME", runtime), \
                    mock.patch.object(control, "SMB_CONFIG", config):
                control.write_smb_config(downloads)

            value = config.read_text(encoding="utf-8")
            self.assertIn("bind interfaces only = yes", value)
            self.assertIn("interfaces = lo eth0", value)
            self.assertIn("hosts deny = 0.0.0.0/0", value)
            self.assertIn("guest ok = yes", value)
            self.assertIn("server min protocol = SMB2_02", value)
            self.assertIn("smb ports = 445", value)
            self.assertIn(f"path = {downloads}", value)

    def test_nfs_export_squashes_all_lan_clients_to_service_user(self):
        settings = {
            "data_path": "/data", "shares": {"nfs_enabled": True},
        }
        account = mock.Mock(pw_uid=100, pw_gid=100)
        run_result = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(control, "load_settings", return_value=settings), \
                mock.patch.object(control, "INSTALLED", mock.Mock(exists=lambda: True)), \
                mock.patch.object(
                    control, "downloads_path",
                    return_value=Path("/data/downloads")), \
                mock.patch.object(control, "nfs_stop"), \
                mock.patch.object(control.pwd, "getpwnam", return_value=account), \
                mock.patch.object(control.Path, "mkdir"), \
                mock.patch.object(control.Path, "exists", return_value=True), \
                mock.patch.object(control, "run", return_value=run_result) as run, \
                mock.patch.object(control, "nfs_running", return_value=True):
            control.nfs_start()

        exports = [call.args[0] for call in run.call_args_list
                   if call.args[0][0] == "/usr/sbin/exportfs"]
        self.assertEqual(len(exports), len(control.LAN_NETWORKS))
        for command in exports:
            self.assertIn("all_squash", command[3])
            self.assertIn("anonuid=100", command[3])
            self.assertIn("anongid=100", command[3])
        run.assert_any_call(
            ["/usr/sbin/rpc.nfsd", "-N", "3", "-V", "4", "-t", "-U", "4"])
        run.assert_any_call(["/usr/sbin/rpc.mountd", "-V", "4", "-u"])

    def test_nfs_stop_does_not_initialize_an_unmounted_server(self):
        with mock.patch.object(
                control, "NFSD_THREADS", mock.Mock(exists=lambda: False)), \
                mock.patch.object(control, "run") as run:
            control.nfs_stop()

        self.assertFalse(any(call.args[0][0] == "/usr/sbin/rpc.nfsd"
                             for call in run.call_args_list))

    def test_nfs_stop_is_explicitly_v4_only(self):
        with mock.patch.object(
                control, "NFSD_THREADS", mock.Mock(exists=lambda: True)), \
                mock.patch.object(control, "run") as run:
            control.nfs_stop()

        run.assert_any_call(
            ["/usr/sbin/rpc.nfsd", "-N", "3", "-V", "4", "0"], check=False)

    def test_nfs_export_retries_a_transient_first_failure(self):
        failed = mock.Mock(returncode=1, stderr="temporarily unavailable")
        succeeded = mock.Mock(returncode=0, stderr="")
        results = [failed, succeeded] + [succeeded] * (len(control.LAN_NETWORKS) - 1)
        with mock.patch.object(control, "run", side_effect=results) as run, \
                mock.patch.object(control.time, "sleep") as sleep:
            control.export_nfs_path(Path("/data/downloads"), "rw,fsid=0")

        self.assertEqual(run.call_count, len(control.LAN_NETWORKS) + 1)
        sleep.assert_called_once_with(0.1)

    def test_traffic_lock_allows_only_marked_wireguard_outer_packets(self):
        firewall = (
            Path(__file__).parents[3]
            / "board/qbtos/common/rootfs-overlay/etc/nftables-qbtos.conf"
        ).read_text(encoding="utf-8")
        outer_rule = (
            'meta skuid "qbtos-qbt" oifname "eth0" '
            "meta mark @wireguard_marks meta l4proto udp accept"
        )
        reject_rule = 'meta skuid "qbtos-qbt" reject'

        self.assertIn("set wireguard_marks", firewall)
        self.assertIn("type mark", firewall)
        self.assertIn(outer_rule, firewall)
        self.assertLess(firewall.index(outer_rule), firewall.index(reject_rule))
        self.assertNotIn(
            'meta skuid "qbtos-qbt" oifname "eth0" accept', firewall)

    def test_wireguard_fwmark_is_validated_and_added_to_nft_set(self):
        result = mock.Mock(stdout="0xca6c\n", returncode=0)
        with mock.patch.object(control, "run", return_value=result) as run:
            self.assertEqual(control.configure_wireguard_firewall(), "0xca6c")

        self.assertEqual(run.call_args_list, [
            mock.call(
                ["/usr/bin/wg", "show", "wg0", "fwmark"], capture=True),
            mock.call([
                "/usr/sbin/nft", "flush", "set", "ip", "qbtos",
                "wireguard_marks",
            ], check=False),
            mock.call([
                "/usr/sbin/nft", "add", "element", "ip", "qbtos",
                "wireguard_marks", "{", "0xca6c", "}",
            ]),
        ])

    def test_wireguard_fwmark_rejects_off_or_malformed_values(self):
        for value in ("off\n", "0\n", "not-a-mark\n", "0x100000000\n"):
            with self.subTest(value=value), mock.patch.object(
                    control, "run",
                    return_value=mock.Mock(stdout=value, returncode=0)) as run:
                with self.assertRaisesRegex(RuntimeError, "invalid fwmark"):
                    control.configure_wireguard_firewall()
                run.assert_called_once_with(
                    ["/usr/bin/wg", "show", "wg0", "fwmark"], capture=True)

    def test_wireguard_protection_requires_mark_in_nft_set(self):
        results = [
            mock.Mock(stdout="0xca6c\n", returncode=0),
            mock.Mock(stdout="", returncode=1),
        ]
        with mock.patch.object(control, "run", side_effect=results):
            with self.assertRaisesRegex(RuntimeError, "traffic lock is not loaded"):
                control.wireguard_firewall_ready()

    def test_wireguard_protection_checks_outer_packet_mark(self):
        results = [
            mock.Mock(stdout="", returncode=0),
            mock.Mock(stdout="2: wg0: <POINTOPOINT,UP>\n", returncode=0),
            mock.Mock(stdout="1.1.1.1 dev wg0\n", returncode=0),
            mock.Mock(stdout="peer-key\t900\n", returncode=0),
        ]
        with mock.patch.object(
                control, "load_settings",
                return_value={"vpn_type": "wireguard"}), \
                mock.patch.object(control, "run", side_effect=results), \
                mock.patch.object(
                    control, "wireguard_firewall_ready", return_value=True
                ) as ready, \
                mock.patch.object(control.time, "time", return_value=1000):
            self.assertTrue(control.vpn_check(verbose=False))

        ready.assert_called_once_with()

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
