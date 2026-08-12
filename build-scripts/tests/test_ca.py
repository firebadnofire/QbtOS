# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
CA_DIR = REPO / "ca"
VALIDATOR = REPO / "br2-external/package/qbtos-ca/validate-ca.sh"
PACKAGE_MK = REPO / "br2-external/package/qbtos-ca/qbtos-ca.mk"
RELEASE_SCRIPT = REPO / "build-scripts/release.sh"
RAUC_CONFIG = (
    REPO / "br2-external/board/qbtos/rpi4/rootfs-overlay/etc/rauc/system.conf"
)


class CertificateTrustTests(unittest.TestCase):
    def test_release_certificate_chains_to_dedicated_root(self):
        subprocess.run([VALIDATOR, shutil.which("openssl"), CA_DIR], check=True)

    def test_private_key_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "ca"
            shutil.copytree(CA_DIR, copied)
            with (copied / "ca-chain.pem").open("a", encoding="ascii") as stream:
                stream.write("-----BEGIN PRIVATE KEY-----\nsecret\n")
            result = subprocess.run(
                [VALIDATOR, shutil.which("openssl"), copied],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private key material", result.stderr)

    def test_qbtos_ca_is_rauc_only_not_system_tls_trust(self):
        package = PACKAGE_MK.read_text(encoding="utf-8")
        config = RAUC_CONFIG.read_text(encoding="utf-8")

        self.assertIn("$(TARGET_DIR)/etc/rauc/keyring.pem", package)
        self.assertNotIn("usr/share/ca-certificates", package)
        self.assertNotIn("etc/ssl", package)
        self.assertIn("path=/etc/rauc/keyring.pem", config)
        self.assertIn("check-purpose=codesign", config)

    def test_bundle_carries_intermediate_without_root(self):
        release = RELEASE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'rauc_intermediate="${repo_root}/ca/intermediate-ca.pem"', release
        )
        self.assertNotIn(
            'rauc_intermediate="${repo_root}/ca/ca-chain.pem"', release
        )

    def test_development_release_uses_an_isolated_self_signed_signer(self):
        release = RELEASE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            "development release requires a distinct development certificate", release
        )
        self.assertIn("development RAUC certificate must be self-signed", release)
        self.assertIn("rauc_signing_keyring=$RAUC_CERT_FILE", release)
        self.assertIn("rauc_intermediate_option=", release)


if __name__ == "__main__":
    unittest.main()
