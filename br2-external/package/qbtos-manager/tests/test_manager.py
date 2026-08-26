# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import http.client
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "src/qbtos_manager.py"
INDEX_PATH = MODULE_PATH.with_name("index.html")
VPN_INIT_PATH = Path(__file__).parents[1] / "S60qbtos-vpn"
CONFIG_IN_PATH = Path(__file__).parents[1] / "Config.in"
PACKAGE_MK_PATH = Path(__file__).parents[1] / "qbtos-manager.mk"
WEB_MUX_INIT_PATH = Path(__file__).parents[1] / "S45qbtos-web-mux"
ARGON_PACKAGE = Path(__file__).parents[2] / "argon40-rust"
PERSISTENCE_INIT_PATH = (
    Path(__file__).parents[3]
    / "board/qbtos/common/rootfs-overlay/etc/init.d/S30qbtos-persistence"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("qbtos_manager", MODULE_PATH)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class ValidationTests(unittest.TestCase):
    def test_argon_uses_pinned_rust_submodule_and_sysv_service(self):
        config = (ARGON_PACKAGE / "Config.in").read_text(encoding="utf-8")
        package = (ARGON_PACKAGE / "argon40-rust.mk").read_text(encoding="utf-8")
        init = (ARGON_PACKAGE / "S85argon40d").read_text(encoding="utf-8")
        cargo = (ARGON_PACKAGE / "source/Cargo.toml").read_text(encoding="utf-8")

        self.assertIn("select BR2_PACKAGE_HOST_RUSTC", config)
        self.assertIn("cbde9ecd2f03d74767f93e78107b2bd788d4bdab", package)
        self.assertIn("$(eval $(cargo-package))", package)
        self.assertIn('name = "argon40"', cargo)
        self.assertIn("--button-actions", init)
        self.assertIn("argon40-shutdown poweroff", init)
        self.assertIn("daemon exited during startup", init)

    def test_theme_git_has_tls_enabled_https_transport(self):
        config = CONFIG_IN_PATH.read_text(encoding="utf-8")

        self.assertIn("select BR2_PACKAGE_GIT", config)
        self.assertIn("select BR2_PACKAGE_LIBCURL", config)
        self.assertIn("select BR2_PACKAGE_LIBCURL_FORCE_TLS", config)

    def test_sslh_multiplexes_http_and_tls_on_both_public_ports(self):
        config = CONFIG_IN_PATH.read_text(encoding="utf-8")
        package = PACKAGE_MK_PATH.read_text(encoding="utf-8")
        init = WEB_MUX_INIT_PATH.read_text(encoding="utf-8")

        self.assertIn("select BR2_PACKAGE_SSLH", config)
        self.assertIn("QBTOS_MANAGER_DEPENDENCIES = sslh", package)
        self.assertIn("$(RM) $(TARGET_DIR)/etc/init.d/S35sslh", package)
        self.assertIn("DAEMON=qbtos-web-mux", init)
        self.assertIn("EXECUTABLE=/usr/sbin/sslh", init)
        self.assertIn('-x "$EXECUTABLE"', init)
        self.assertIn(
            'start_mux "$MANAGER_PIDFILE" 8080 18443 18080', init)
        self.assertIn(
            'start_mux "$QBITTORRENT_PIDFILE" 8081 18444 18081', init)
        self.assertIn('--on-timeout tls', init)
        self.assertIn('sslh failed to stay running on port %s', init)

    def test_saved_vpn_is_restored_before_qbittorrent_init(self):
        script = VPN_INIT_PATH.read_text(encoding="utf-8")

        self.assertIn('/config/qbtos/state/installed', script)
        self.assertIn('qbtos-control vpn-start', script)
        self.assertLess(VPN_INIT_PATH.name, "S70qbittorrent")

    def test_persistent_clock_prevents_wireguard_timestamp_rollback(self):
        script = PERSISTENCE_INIT_PATH.read_text(encoding="utf-8")
        control = (MODULE_PATH.parent / "qbtos_control.py").read_text(encoding="utf-8")

        self.assertIn("restore_clock_floor", script)
        self.assertIn("target_epoch=$((saved_epoch + 1))", script)
        self.assertIn("qbtos-control clock-save", script)
        self.assertIn("clock_save()", control)

    def test_qbittorrent_navigation_suppresses_cross_origin_referrer(self):
        page = INDEX_PATH.read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn('<meta name="referrer" content="no-referrer">', page)
        self.assertIn('referrerpolicy="no-referrer"', page)
        self.assertIn('rel="noreferrer noopener"', page)
        self.assertIn('"Referrer-Policy", "no-referrer"', source)

    def test_ui_documents_plain_http_upgrade(self):
        page = INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "Plaintext HTTP on ports 8080 and 8081 redirects", page)

    def test_successful_install_redirects_to_qbittorrent(self):
        page = INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn("path === '/api/complete'", page)
        self.assertIn("window.location.replace(qbtUrl())", page)
        self.assertIn("https://${location.hostname}:8081/", page)

    def test_setup_requires_matching_administrator_passwords(self):
        page = INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn('id="qb_password_confirmation"', page)
        self.assertIn('name="qb_password_confirmation"', page)
        self.assertIn('autocomplete="new-password" required', page)
        self.assertIn("validatePasswordConfirmation()", page)
        self.assertIn("if (!form.reportValidity()) return", page)

        with self.assertRaisesRegex(
                manager.ValidationError, "Administrator passwords do not match"):
            manager.persist_setup({
                "qb_username": "admin",
                "qb_password": "secure password",
                "qb_password_confirmation": "mistyped password",
            })

        manager.validate_account("admin", "secure password", "secure password")

    def test_installed_ui_hides_setup_and_exposes_theme_actions(self):
        page = INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn("form.hidden = status.installed", page)
        self.assertIn("/api/themes/install", page)
        self.assertIn("/api/themes/update", page)
        self.assertIn("/api/themes/select", page)

    def test_installed_ui_exposes_qbittorrent_controls_and_status(self):
        page = INDEX_PATH.read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")

        for operation in ("start", "stop", "restart"):
            self.assertIn(f"/api/qbittorrent/{operation}", source)
            self.assertIn(f"qbittorrentCall('{operation}')", page)
        self.assertIn('id="qbittorrent-status"', page)
        self.assertIn('status.persistence', page)

    def test_update_ui_has_default_feed_status_and_action_gates(self):
        page = INDEX_PATH.read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")
        feed = (
            "https://raw.githubusercontent.com/firebadnofire/QbtOS/"
            "refs/heads/update-feed/latest.json")

        self.assertEqual(manager.UPDATE_FEED_DEFAULT, feed)
        self.assertEqual(page.count(f'value="{feed}"'), 2)
        for element in (
                "update-state", "update-current", "update-available",
                "update-checked", "update-detail", "update-progress"):
            self.assertIn(f'id="{element}"', page)
        self.assertIn("update.update_available", page)
        self.assertIn("update.download_ready", page)
        self.assertIn("update.reboot_pending", page)
        self.assertIn("formatTimestamp(update.last_checked_at)", page)
        self.assertIn('"checking", 0, "Checking the signed update feed"', source)
        self.assertIn('"failed", 0, f"Update check failed:', source)
        self.assertIn('"failed", 0, f"Update verification failed:', source)

    def test_update_feed_api_falls_back_to_shipped_default(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text('{"update_feed_url": ""}\n', encoding="utf-8")
            with mock.patch.object(manager, "SETTINGS", settings):
                self.assertEqual(
                    manager.update_feed_url({}), manager.UPDATE_FEED_DEFAULT)
                with self.assertRaises(manager.ValidationError):
                    manager.update_feed_url({"update_feed_url": ""})

    def test_update_verification_failure_is_persisted_and_stops_download(self):
        error = manager.qbtos_update.UpdateError("signature rejected")
        with mock.patch.object(
                manager.qbtos_update, "verify_release_checksums",
                side_effect=error), mock.patch.object(
                    manager.qbtos_update, "download_bundle") as download, \
                mock.patch.object(
                    manager.qbtos_update, "set_update_status") as status:
            with self.assertRaises(manager.qbtos_update.UpdateError):
                manager.download_update({})

        status.assert_called_once_with(
            "failed", 0,
            "Update verification failed: signature rejected")
        download.assert_not_called()

    def test_installed_ui_can_retry_vpn_and_start_qbittorrent(self):
        page = INDEX_PATH.read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="retry-vpn"', page)
        self.assertIn("fetch('/api/vpn/retry'", page)
        self.assertIn('"/api/vpn/retry"', source)
        self.assertIn('control("vpn-start", timeout=120)', source)
        self.assertIn('control("qbt-start")', source)

    def test_installed_ui_controls_lan_file_shares(self):
        page = INDEX_PATH.read_text(encoding="utf-8")
        source = MODULE_PATH.read_text(encoding="utf-8")
        config = CONFIG_IN_PATH.read_text(encoding="utf-8")

        self.assertIn('id="file-sharing"', page)
        self.assertIn("shareCall(protocol, operation)", page)
        self.assertIn("/api/shares/smb/enable", source)
        self.assertIn("/api/shares/nfs/enable", source)
        self.assertIn("select BR2_PACKAGE_SAMBA4", config)
        self.assertIn("select BR2_PACKAGE_NFS_UTILS_NFSV4", config)

    def test_share_enablement_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text('{"version": 1}\n', encoding="utf-8")
            with mock.patch.object(manager, "SETTINGS", settings):
                manager.set_share_enabled("smb", True)
                manager.set_share_enabled("nfs", False)

            value = manager.json.loads(settings.read_text(encoding="utf-8"))
            self.assertTrue(value["shares"]["smb_enabled"])
            self.assertFalse(value["shares"]["nfs_enabled"])

    def test_atomic_write_syncs_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state" / "installed"
            manager.atomic_write(destination, "installed\n")

            self.assertEqual(destination.read_text(encoding="utf-8"), "installed\n")

    def test_password_hash_round_trip(self):
        encoded = manager.password_hash("correct horse battery staple", salt=b"0" * 16)
        self.assertTrue(manager.verify_password(encoded, "correct horse battery staple"))
        self.assertFalse(manager.verify_password(encoded, "wrong password"))

    def test_qbittorrent_hash_shape(self):
        encoded = manager.qbittorrent_password_hash("development password")
        salt, digest = encoded.split(":")
        self.assertEqual(len(manager.base64.b64decode(salt)), 16)
        self.assertEqual(len(manager.base64.b64decode(digest)), 64)

    def test_qbittorrent_webui_reuses_manager_tls_identity(self):
        config = manager.add_qbittorrent_https(
            "[Preferences]\nWebUI\\HTTPS\\Enabled=false\n"
            "WebUI\\HostHeaderValidation=true\n"
            "WebUI\\LocalHostAuth=false\n"
            "WebUI\\CSRFProtection=false\n"
            "WebUI\\ClickjackingProtection=false\n"
            "WebUI\\SecureCookie=false\n"
            "WebUI\\Port=8081\n\n[Other]\nValue=true\n")

        self.assertIn(
            f"WebUI\\HTTPS\\CertificatePath={manager.TLS_CERT}", config)
        self.assertIn("WebUI\\HTTPS\\Enabled=true", config)
        self.assertIn(f"WebUI\\HTTPS\\KeyPath={manager.TLS_KEY}", config)
        self.assertIn(f"WebUI\\Address={manager.LOOPBACK}", config)
        self.assertIn(
            f"WebUI\\Port={manager.QBITTORRENT_TLS_PORT}", config)
        self.assertIn("WebUI\\HostHeaderValidation=false", config)
        self.assertIn("WebUI\\LocalHostAuth=true", config)
        self.assertIn("WebUI\\CSRFProtection=true", config)
        self.assertIn("WebUI\\ClickjackingProtection=true", config)
        self.assertIn("WebUI\\SecureCookie=true", config)
        self.assertNotIn("WebUI\\Port=8081", config)
        self.assertNotIn("WebUI\\HTTPS\\Enabled=false", config)
        self.assertNotIn("WebUI\\HostHeaderValidation=true", config)
        self.assertNotIn("WebUI\\LocalHostAuth=false", config)
        self.assertNotIn("WebUI\\CSRFProtection=false", config)
        self.assertNotIn("WebUI\\ClickjackingProtection=false", config)
        self.assertNotIn("WebUI\\SecureCookie=false", config)
        self.assertLess(
            config.index("WebUI\\HTTPS\\Enabled=true"),
            config.index("[Other]"))

    def test_plain_http_redirect_preserves_safe_host_path_and_method(self):
        server = manager.http.server.ThreadingHTTPServer(
            (manager.LOOPBACK, 0), manager.RedirectHandler)
        server.redirect_fallback_host = "192.168.1.20"
        server.redirect_public_port = manager.MANAGER_PUBLIC_PORT
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request(
                "PROPFIND", "/api/test?value=1", body=b"ignored",
                headers={"Host": "192.168.1.30:8080"})
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 308)
            self.assertEqual(
                response.getheader("Location"),
                "https://192.168.1.30:8080/api/test?value=1")
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.getheader("Content-Length"), "0")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_plain_http_redirect_rejects_untrusted_host_header(self):
        self.assertEqual(
            manager.safe_redirect_host("attacker.example:8081", "192.168.1.20"),
            "192.168.1.20")

    def test_wireguard_full_tunnel_is_normalized(self):
        config = """[Interface]
PrivateKey = secret
Address = 10.0.0.2/32
DNS = 10.0.0.1
[Peer]
PublicKey = public
Endpoint = vpn.example:51820
AllowedIPs = 0.0.0.0/0
"""
        normalized, dns = manager.validate_wireguard(config)
        self.assertNotIn("DNS", normalized)
        self.assertEqual(dns, ["10.0.0.1"])

    def test_wireguard_dual_stack_profile_is_normalized_to_ipv4(self):
        config = """[Interface]
PrivateKey = secret
Address = 10.0.0.2/32, fd00::2/128
DNS = 10.0.0.1, fd00::1
[Peer]
PublicKey = public
Endpoint = vpn.example:51820
AllowedIPs = 0.0.0.0/0, ::/0
"""
        normalized, dns = manager.validate_wireguard(config)
        self.assertIn("Address = 10.0.0.2/32", normalized)
        self.assertIn("AllowedIPs = 0.0.0.0/0", normalized)
        self.assertNotIn("fd00::", normalized)
        self.assertNotIn("::/0", normalized)
        self.assertEqual(dns, ["10.0.0.1"])

    def test_wireguard_rejects_command_hooks(self):
        with self.assertRaises(manager.ValidationError):
            manager.validate_wireguard("""[Interface]
PrivateKey=x
Address=10.0.0.2/32
PostUp=curl example.invalid
[Peer]
PublicKey=y
Endpoint=host:1
AllowedIPs=0.0.0.0/0
""")

    def test_openvpn_requires_full_tunnel(self):
        with self.assertRaises(manager.ValidationError):
            manager.validate_openvpn("client\nremote vpn.example 1194\ndev tun\n")

    def test_openvpn_rejects_script_execution(self):
        with self.assertRaises(manager.ValidationError):
            manager.validate_openvpn(
                "client\nremote vpn.example 1194\nredirect-gateway def1\nup /tmp/run-me\n")

    def test_data_path_accepts_mounted_test_root(self):
        with tempfile.TemporaryDirectory() as directory:
            # The temporary filesystem's mount point is outside the production roots,
            # so inject it as the sole permitted root for this unit test.
            root = Path(directory).resolve()
            with mock.patch.object(manager.os.path, "ismount", return_value=True):
                self.assertEqual(
                    manager.validate_data_path(directory, roots=(str(root),)), str(root))


if __name__ == "__main__":
    unittest.main()
