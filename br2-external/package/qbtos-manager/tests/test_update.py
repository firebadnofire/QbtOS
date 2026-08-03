# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
update = importlib.import_module("qbtos_update")
boot_confirm = importlib.import_module("qbtos_boot_confirm")


def feed(payload=b"signed bundle", revision=2):
    version = f"2026-08-02-rev{revision}"
    return {
        "schema": 1,
        "version": version,
        "build_date": "2026-08-02",
        "revision": revision,
        "source_tag": f"revision-{revision}",
        "commit": "a" * 40,
        "compatible": "qbtos-rpi4",
        "channel": "stable",
        "bundle_filename": f"{version}.raucb",
        "image_filename": f"{version}.img.zst",
        "checksum_filename": f"{version}.sha256",
        "bundle_sha256": hashlib.sha256(payload).hexdigest(),
        "image_sha256": "b" * 64,
        "bundle_size": len(payload),
        "image_size": 123,
        "bundle_url": f"https://updates.example.test/{version}.raucb",
        "image_url": f"https://updates.example.test/{version}.img.zst",
        "checksum_url": f"https://updates.example.test/{version}.sha256",
    }


CURRENT = {
    "version": "2026-08-01-rev1", "revision": 1,
    "compatible": "qbtos-rpi4", "channel": "stable",
}


class Response:
    def __init__(self, payload, status=200, fail_after=None):
        self.stream = io.BytesIO(payload)
        self.status = status
        self.fail_after = fail_after
        self.read_total = 0

    def read(self, size=-1):
        if self.fail_after is not None and self.read_total >= self.fail_after:
            raise OSError("simulated interruption")
        if self.fail_after is not None:
            size = min(size, self.fail_after - self.read_total)
        value = self.stream.read(size)
        self.read_total += len(value)
        return value

    def getcode(self):
        return self.status


class UpdateValidationTests(unittest.TestCase):
    def test_openpgp_checksums_bind_feed_to_bundle(self):
        document = feed()
        checksum_text = (
            f"{document['image_sha256']}  {document['image_filename']}\n"
            f"{document['bundle_sha256']}  {document['bundle_filename']}\n"
            f"{'c' * 64}  {document['version']}.manifest.json\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keyring = root / "trusted.gpg"
            keyring.write_bytes(b"public key")

            def verify(command, **kwargs):
                del kwargs
                output = Path(command[command.index("--output") + 1])
                output.write_text(checksum_text, encoding="ascii")
                return types.SimpleNamespace(returncode=0)

            entries = update.verify_release_checksums(
                document, root=root,
                opener=lambda *args, **kwargs: Response(b"clear-signed checksums"),
                runner=verify, keyring=keyring)
            self.assertEqual(entries[document["bundle_filename"]],
                             document["bundle_sha256"])

    def test_openpgp_signature_failure_rejected(self):
        document = feed()
        with tempfile.TemporaryDirectory() as directory:
            keyring = Path(directory) / "trusted.gpg"
            keyring.write_bytes(b"public key")
            with self.assertRaises(update.UpdateError):
                update.verify_release_checksums(
                    document, root=directory,
                    opener=lambda *args, **kwargs: Response(b"tampered"),
                    runner=lambda *args, **kwargs: types.SimpleNamespace(returncode=1),
                    keyring=keyring)

    def test_incompatible_bundle_rejected(self):
        document = feed()
        document["compatible"] = "different-board"
        with self.assertRaises(update.UpdateError):
            update.validate_feed(document, CURRENT)

    def test_downgrade_rejected(self):
        with self.assertRaises(update.UpdateError):
            update.validate_feed(feed(revision=1), {**CURRENT, "revision": 2})

    def test_checksum_mismatch_removes_partial(self):
        document = feed(payload=b"expected")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(update.UpdateError):
                update.download_bundle(
                    document, root=root,
                    opener=lambda *args, **kwargs: Response(b"tampered"))
            self.assertFalse((root / f".{document['bundle_filename']}.part").exists())

    def test_interrupted_download_resumes(self):
        payload = b"0123456789"
        document = feed(payload=payload)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(update.UpdateError):
                update.download_bundle(
                    document, root=root,
                    opener=lambda *args, **kwargs: Response(payload, fail_after=4))
            partial = root / f".{document['bundle_filename']}.part"
            self.assertEqual(partial.read_bytes(), payload[:4])

            def resume(request, **kwargs):
                self.assertEqual(request.headers["Range"], "bytes=4-")
                return Response(payload[4:], status=206)

            final = update.download_bundle(document, root=root, opener=resume)
            self.assertEqual(final.read_bytes(), payload)

    def test_active_slot_never_selected_as_target(self):
        self.assertEqual(update.inactive_slot("A"), "B")
        self.assertEqual(update.inactive_slot("B"), "A")
        with self.assertRaises(update.UpdateError):
            update.inactive_slot("unknown")

    def test_three_failed_pending_boots_fall_back(self):
        attempts = {"A": 3, "B": 3}
        selected = []
        for _ in range(3):
            slot, attempts = update.choose_boot_slot("B A", attempts)
            selected.append(slot)
        slot, attempts = update.choose_boot_slot("B A", attempts)
        self.assertEqual(selected, ["B", "B", "B"])
        self.assertEqual(slot, "A")


class MigrationTests(unittest.TestCase):
    def _state(self, base):
        root = Path(base) / "qbtos"
        root.mkdir()
        (root / "state").mkdir()
        (root / "state/schema-version").write_text("1\n", encoding="ascii")
        (root / "settings.json").write_text(
            json.dumps({"version": 1, "value": "original"}), encoding="utf-8")
        return root, Path(base) / "qbtos-state"

    def test_migration_failure_keeps_active_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, container = self._state(directory)

            def fail(candidate):
                (candidate / "settings.json").write_text("{}", encoding="utf-8")
                raise update.UpdateError("simulated migration failure")

            with self.assertRaises(update.UpdateError):
                update.migrate_state(2, {1: fail}, root=root, container=container)
            active = root.resolve()
            value = json.loads((active / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(value["value"], "original")
            self.assertEqual(update._schema_of(active), 1)

    def test_active_generation_allows_service_user_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root, container = self._state(directory)
            active = update.migrate_state(1, root=root, container=container)
            self.assertEqual(active.stat().st_mode & 0o777, 0o711)
            self.assertEqual((container / "generations").stat().st_mode & 0o777, 0o711)

    def test_rollback_restores_pre_update_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root, container = self._state(directory)
            update.prepare_state_backup(root=root, container=container)

            def migrate(candidate):
                value = json.loads((candidate / "settings.json").read_text(encoding="utf-8"))
                value["value"] = "new"
                (candidate / "settings.json").write_text(json.dumps(value), encoding="utf-8")

            update.migrate_state(2, {1: migrate}, root=root, container=container)
            self.assertEqual(update._schema_of(root.resolve()), 2)
            update.migrate_state(1, root=root, container=container)
            restored = json.loads((root.resolve() / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(restored["value"], "original")


class BootConfirmationTests(unittest.TestCase):
    def test_boot_health_has_no_internet_or_provider_dependency(self):
        with mock.patch.object(boot_confirm, "state_is_writable", return_value=True), \
                mock.patch.object(boot_confirm, "manager_is_healthy", return_value=True), \
                mock.patch.object(boot_confirm, "firewall_is_healthy", return_value=True), \
                mock.patch.object(boot_confirm, "qbittorrent_is_safe", return_value=True), \
                mock.patch.object(update, "target_schema", return_value=1), \
                mock.patch.object(update, "validate_state", return_value=True):
            checks = boot_confirm.local_health_checks()
        self.assertTrue(all(checks.values()))
        self.assertNotIn("internet", checks)
        self.assertNotIn("vpn_provider", checks)
        self.assertNotIn("vpn_connected", checks)


if __name__ == "__main__":
    unittest.main()
