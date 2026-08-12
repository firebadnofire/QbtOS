# SPDX-License-Identifier: GPL-3.0-or-later

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parents[2]
VERSION_SCRIPT = REPO / "build-scripts/release-version.sh"
MANIFEST_SCRIPT = REPO / "build-scripts/release-manifest.py"
FORGEJO_WORKFLOW = REPO / ".forgejo/workflows/release.yml"
FORGEJO_PUBLISH = REPO / "build-scripts/publish-forgejo-release.sh"


class TemporaryRepository:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.email", "tests@qbtos.invalid")
        self.git("config", "user.name", "qbtOS tests")
        self.git("config", "commit.gpgSign", "false")
        self.git("config", "tag.gpgSign", "false")
        (self.path / "tracked").write_text("initial\n", encoding="utf-8")
        self.git("add", "tracked")
        self.git("commit", "-qm", "initial")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()

    def commit(self):
        with (self.path / "tracked").open("a", encoding="utf-8") as stream:
            stream.write("next\n")
        self.git("commit", "-qam", "next")

    def version(self):
        return subprocess.run([VERSION_SCRIPT], cwd=self.path, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def close(self):
        self.temporary.cleanup()


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.repo = TemporaryRepository()

    def tearDown(self):
        self.repo.close()

    def test_no_revision_tag_is_rejected(self):
        result = self.repo.version()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no reachable revision-N", result.stderr)

    def test_revision_order_is_numeric(self):
        self.repo.git("tag", "revision-9")
        self.repo.git("tag", "revision-10")
        result = self.repo.version()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVISION='10'", result.stdout)
        self.assertIn("SOURCE_TAG='revision-10'", result.stdout)

    def test_commits_after_tag_keep_revision(self):
        self.repo.git("tag", "revision-2")
        self.repo.commit()
        result = self.repo.version()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVISION='2'", result.stdout)
        self.assertIn(f"COMMIT='{self.repo.git('rev-parse', 'HEAD')}'", result.stdout)

    def test_malformed_and_misspelled_tags_are_rejected(self):
        for tag in ("revision-0", "revision-01", "revision-x", "revsion-3"):
            with self.subTest(tag=tag):
                repository = TemporaryRepository()
                try:
                    repository.git("tag", "revision-1")
                    repository.git("tag", tag)
                    result = repository.version()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("invalid reachable revision tag", result.stderr)
                finally:
                    repository.close()


class ManifestTests(unittest.TestCase):
    def test_manifest_creation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "2026-08-02-rev1.raucb"
            image = root / "2026-08-02-rev1.img.zst"
            bundle.write_bytes(b"bundle")
            image.write_bytes(b"image")
            outputs = [root / "one.json", root / "two.json"]
            common = [
                MANIFEST_SCRIPT, "--version", "2026-08-02-rev1",
                "--build-date", "2026-08-02", "--revision", "1",
                "--source-tag", "revision-1", "--commit", "a" * 40,
                "--bundle", bundle, "--image", image,
            ]
            for output in outputs:
                subprocess.run([*map(str, common), "--output", str(output)], check=True)
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            value = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], 1)
            self.assertEqual(value["bundle_filename"], bundle.name)
            self.assertEqual(value["checksum_filename"], "2026-08-02-rev1.sha256")


class ForgejoWorkflowTests(unittest.TestCase):
    def test_every_revision_tag_triggers_an_exact_validated_release(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('tags:\n      - "revision-*"', workflow)
        self.assertIn("container: node:22-bookworm", workflow)
        self.assertIn("Install build dependencies", workflow)
        self.assertIn("QBTOS_REF_NAME: ${{ forgejo.ref_name }}", workflow)
        self.assertIn("git describe --tags --exact-match HEAD", workflow)
        self.assertIn("Missing required Forgejo secret", workflow)
        self.assertIn("for required_secret in RAUC_CERT_PEM RAUC_KEY_PEM CI_KEY", workflow)
        self.assertIn('^revision-[1-9][0-9]*$', workflow)
        self.assertIn('eval "$(./build-scripts/release-version.sh)"', workflow)
        self.assertIn('[[ "$SOURCE_TAG" == "$ref_name" ]]', workflow)
        self.assertIn("printf 'VERSION=%s\\n'", workflow)
        self.assertIn("publish-forgejo-release.sh", workflow)

    def test_feed_branch_uses_forgejo_branch_api(self):
        publish = FORGEJO_PUBLISH.read_text(encoding="utf-8")
        self.assertIn("new_branch_name:$branch,old_ref_name:$source", publish)
        self.assertIn('"${api}/branches"', publish)
        self.assertNotIn('"${api}/git/refs"', publish)

    def test_shared_openpgp_secret_is_decoded_before_import(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("key_file=\"$gnupg_home/release-signing-key\"", workflow)
        self.assertIn("-----BEGIN PGP PRIVATE KEY BLOCK-----", workflow)
        self.assertIn("base64 --decode > \"$key_file\"", workflow)
        self.assertIn('gpg --batch --import "$key_file"', workflow)
        self.assertNotIn(
            'printf \'%s\\n\' "$CI_KEY" | GNUPGHOME="$gnupg_home"', workflow
        )

    def test_openpgp_signer_selection_and_cleanup_are_fail_closed(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--with-colons", workflow)
        self.assertIn('"${#signing_fingerprints[@]}" -ne 1', workflow)
        self.assertIn("QBTOS_GPG_FINGERPRINT=%s", workflow)
        self.assertIn("CI_TRUSTED_PUBLIC_KEYS", workflow)
        self.assertIn('gpg --batch --export \\\n', workflow)
        self.assertNotIn("--export-secret", workflow)
        self.assertIn('if: always()', workflow)
        self.assertIn(
            'rm -f "$RUNNER_TEMP/qbtos-release-gnupg/release-signing-key"',
            workflow,
        )
        self.assertIn(
            'rm -rf -- "$RUNNER_TEMP/qbtos-release-gnupg"', workflow
        )

    def test_checksum_signature_is_verified_before_publication(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--pinentry-mode loopback --passphrase-fd 0", workflow)
        self.assertIn("--armor --clearsign", workflow)
        self.assertIn('--verify "dist/$VERSION.sha256"', workflow)
        self.assertIn('gpg --batch --decrypt \\\n', workflow)
        self.assertIn('"$VERSION.sha256" | sha256sum -c -', workflow)
        self.assertIn('find dist -maxdepth 1 -type f | wc -l', workflow)

    def test_buildroot_release_runs_as_unprivileged_node_user(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Dependency installation UID: %s", workflow)
        self.assertIn('test "$(id -u)" -eq 0', workflow)
        self.assertIn("build_user=node", workflow)
        self.assertIn('chown -R "$build_user:$build_user" "$workspace"', workflow)
        self.assertIn('runuser --user "$build_user" -- env', workflow)
        self.assertIn('printf "Build UID: %s\\n" "$(id -u)"', workflow)
        self.assertIn('test "$(id -u)" -ne 0', workflow)
        self.assertNotIn("FORCE_UNSAFE_CONFIGURE", workflow)

    def test_unprivileged_build_inputs_remain_private(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('chgrp "$build_user" "$RUNNER_TEMP"', workflow)
        self.assertIn('chmod g+x "$RUNNER_TEMP"', workflow)
        self.assertIn('chmod 0600 "$signing_file"', workflow)
        self.assertIn('stat -c \'%a\' "$signing_file"', workflow)
        self.assertIn('test -r "$RAUC_KEY_FILE"', workflow)
        self.assertNotIn("chmod 0644", workflow)


if __name__ == "__main__":
    unittest.main()
