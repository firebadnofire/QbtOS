# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "src/qbtos_manager.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("qbtos_manager", MODULE_PATH)
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class ValidationTests(unittest.TestCase):
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
            "WebUI\\Port=8081\n\n[Other]\nValue=true\n")

        self.assertIn(
            f"WebUI\\HTTPS\\CertificatePath={manager.TLS_CERT}", config)
        self.assertIn("WebUI\\HTTPS\\Enabled=true", config)
        self.assertIn(f"WebUI\\HTTPS\\KeyPath={manager.TLS_KEY}", config)
        self.assertNotIn("WebUI\\HTTPS\\Enabled=false", config)
        self.assertLess(
            config.index("WebUI\\HTTPS\\Enabled=true"),
            config.index("[Other]"))

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
