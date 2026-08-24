# SPDX-License-Identifier: GPL-3.0-or-later

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parents[2]
VERSION_SCRIPT = REPO / "build-scripts/release-version.sh"
MANIFEST_SCRIPT = REPO / "build-scripts/release-manifest.py"
RELEASE_SCRIPT = REPO / "build-scripts/release.sh"
FORGEJO_WORKFLOW = REPO / ".forgejo/workflows/release.yml"
FORGEJO_PUBLISH = REPO / "build-scripts/publish-forgejo-release.sh"
GITHUB_PUBLISH = REPO / "build-scripts/publish-github-release.sh"
CI_RUN = REPO / "build-scripts/ci-run.sh"
CI_RELEASE = REPO / "build-scripts/ci-release.sh"
RELEASE_HANDOFF = REPO / "build-scripts/prepare-release-build.sh"
RELEASE_HANDOFF_TEST = REPO / "build-scripts/tests/test-release-handoff.sh"
RPI4_DEFCONFIG = REPO / "br2-external/configs/qbtos_rpi4_defconfig"


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


class ReleaseScriptTests(unittest.TestCase):
    TRUSTED_GPG_FINGERPRINT = "7D6EF134D851C8DA0862D97494F31AF374E2EE3C"

    def test_rauc_uses_buildroot_host_helpers(self):
        script = RELEASE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('host_dir="${release_output}/host"', script)
        self.assertIn('test -x "${host_dir}/bin/mksquashfs"', script)
        self.assertIn(
            'host_path="${host_dir}/bin:${host_dir}/sbin:${PATH}"', script)
        self.assertEqual(
            script.count('-C keyring:check-purpose=codesign'), 3)
        self.assertIn(
            '-C keyring:check-purpose=codesign bundle', script)
        self.assertIn(
            '-C keyring:check-purpose=codesign info', script)

    def test_openpgp_keyring_is_pinned_before_build(self):
        script = RELEASE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            f"qbtos_gpg_fingerprint={self.TRUSTED_GPG_FINGERPRINT}", script)
        self.assertIn("gpg --batch --show-keys --with-colons", script)
        self.assertIn(
            "must contain exactly one primary OpenPGP key", script)
        self.assertLess(
            script.index("gpg --batch --show-keys --with-colons"),
            script.index('"${script_dir}/build.sh" --format flat'),
        )


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

    def test_feed_creation_uses_post_and_updates_use_put(self):
        publish = FORGEJO_PUBLISH.read_text(encoding="utf-8")

        self.assertIn("content_method=POST", publish)
        self.assertIn("content_method=PUT", publish)
        self.assertIn('-X "$content_method"', publish)
        self.assertIn("--arg source 'main'", publish)
        self.assertIn("--fail-with-body", publish)

    def test_partial_release_rerun_reconciles_managed_assets(self):
        publish = FORGEJO_PUBLISH.read_text(encoding="utf-8")

        self.assertIn("reusing release", publish)
        self.assertIn('select(.name == $name)', publish)
        self.assertIn('cp "$response" "$asset_list"', publish)
        self.assertIn("forgejo-assets.json", publish)
        self.assertNotIn("jq -r '.[].id'", publish)

    def test_release_is_mirrored_to_github_with_existing_secret(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")
        publish = GITHUB_PUBLISH.read_text(encoding="utf-8")

        self.assertIn("Mirror GitHub release", workflow)
        self.assertIn("GH_KEY: ${{ secrets.GH_KEY }}", workflow)
        self.assertIn("firebadnofire/qbtos", workflow)
        self.assertIn(': "${GH_KEY:?GH_KEY is required}"', publish)
        self.assertIn("api.github.com/repos/${repository}", publish)
        self.assertIn("uploads.github.com/repos/${repository}", publish)
        self.assertIn("github-assets.json", publish)
        self.assertIn("--fail-with-body", publish)
        self.assertNotIn("set -x", publish)

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
        self.assertIn(
            "trusted_fingerprint=7D6EF134D851C8DA0862D97494F31AF374E2EE3C",
            workflow,
        )
        self.assertIn(
            'gpg --batch --export "$trusted_fingerprint"', workflow)
        self.assertIn("CI_TRUSTED_PUBLIC_KEYS", workflow)
        self.assertIn(
            'gpg --batch --export "$trusted_fingerprint" \\\n', workflow)
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
        ci_release = CI_RELEASE.read_text(encoding="utf-8")
        handoff = RELEASE_HANDOFF.read_text(encoding="utf-8")

        self.assertIn("Dependency installation UID: %s", workflow)
        self.assertIn('test "$(id -u)" -eq 0', workflow)
        self.assertIn("build_user=node", workflow)
        self.assertIn("test-release-handoff.sh", workflow)
        self.assertIn("prepare-release-build.sh", workflow)
        self.assertIn('runuser --user "$build_user" -- env', handoff)
        self.assertIn('[[ "$(id -u)" -ne 0 ]]', ci_release)
        self.assertNotIn('chown -R "$build_user:$build_user" "$workspace"', workflow)
        self.assertNotIn('chown -R "$build_uid:$build_gid" "$workspace"', handoff)
        self.assertNotIn("FORCE_UNSAFE_CONFIGURE", workflow)
        self.assertNotIn("FORCE_UNSAFE_CONFIGURE", ci_release)
        self.assertNotIn("FORCE_UNSAFE_CONFIGURE", handoff)

    def test_unprivileged_build_inputs_remain_private(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")
        ci_release = CI_RELEASE.read_text(encoding="utf-8")
        handoff = RELEASE_HANDOFF.read_text(encoding="utf-8")
        handoff_test = RELEASE_HANDOFF_TEST.read_text(encoding="utf-8")

        self.assertNotIn('chgrp "$build_user" "$RUNNER_TEMP"', workflow)
        self.assertNotIn('chmod g+x "$RUNNER_TEMP"', workflow)
        self.assertIn("mktemp -d /tmp/qbtos-release-handoff.XXXXXX", handoff)
        self.assertEqual(handoff.count('-m 0600 \\\n'), 3)
        self.assertIn('trap cleanup EXIT', handoff)
        self.assertIn("trap 'exit 1' HUP INT TERM", handoff)
        self.assertIn('[[ ! -e "$private_copy_path" ]]', handoff_test)
        self.assertIn('source-tree ownership changed', handoff_test)
        self.assertIn('[[ -r "$signing_file" ]]', ci_release)
        self.assertNotIn("chmod 0644", workflow)
        self.assertNotIn("chmod 0644", ci_release)
        self.assertNotIn("chmod 0644", handoff)

    def test_ci_build_is_verbose_bounded_and_diagnosable(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")
        build_script = (REPO / "build-scripts/build.sh").read_text(
            encoding="utf-8")
        ci_run = CI_RUN.read_text(encoding="utf-8")
        ci_release = CI_RELEASE.read_text(encoding="utf-8")
        handoff = RELEASE_HANDOFF.read_text(encoding="utf-8")

        self.assertIn("apt-get -qq update", workflow)
        self.assertIn("apt-get -qq install", workflow)
        self.assertIn("QBTOS_BUILD_QUIET=0", workflow)
        self.assertIn("QBTOS_BUILD_JOBS", workflow)
        self.assertIn(
            'QBTOS_BUILD_JOBS="${QBTOS_BUILD_JOBS:-}"', handoff)
        self.assertIn("ci-run.sh", ci_release)
        self.assertIn("output/ci/release-build.log", ci_release)
        self.assertIn("ci-release.sh", workflow)
        self.assertIn("make --silent --no-print-directory check", ci_release)
        self.assertIn("make --silent --no-print-directory release", ci_release)
        self.assertIn("CI phase: signed ARM64 release", ci_release)
        self.assertIn('JOBS="$QBTOS_BUILD_JOBS"', ci_release)
        self.assertIn('QBTOS_BUILD_QUIET:-0', build_script)
        self.assertIn("buildroot_make=(make --silent --no-print-directory", build_script)
        self.assertIn("cgroup_memory_events", ci_run)
        self.assertIn("command_exit_status", ci_run)
        self.assertNotIn("printenv", ci_run)
        self.assertNotIn("env |", ci_run)

    def test_buildroot_caches_are_scoped_and_refreshable(self):
        workflow = FORGEJO_WORKFLOW.read_text(encoding="utf-8")
        ci_release = CI_RELEASE.read_text(encoding="utf-8")
        release = RELEASE_SCRIPT.read_text(encoding="utf-8")
        defconfig = RPI4_DEFCONFIG.read_text(encoding="utf-8")
        restore_steps = workflow[
            workflow.index("Restore Buildroot source downloads"):
            workflow.index("Validate tag and derive release metadata")
        ]
        save_steps = workflow[
            workflow.index("Save Buildroot compiler cache"):
            workflow.index("Sign and verify release checksums")
        ]
        compiler_save_step = save_steps[
            save_steps.index("Save Buildroot compiler cache"):
            save_steps.index("Save Buildroot source downloads")
        ]
        download_save_step = save_steps[
            save_steps.index("Save Buildroot source downloads"):
        ]

        self.assertEqual(workflow.count("uses: actions/cache/restore@v4"), 2)
        self.assertEqual(workflow.count("uses: actions/cache/save@v4"), 2)
        self.assertNotIn("uses: actions/cache@v4", workflow)
        self.assertNotIn("data.forgejo.org/actions/cache", workflow)
        self.assertIn(".ci-cache/buildroot-dl", restore_steps)
        self.assertIn(".ci-cache/buildroot-ccache", restore_steps)
        self.assertIn("runner.os", restore_steps)
        self.assertIn("runner.arch", restore_steps)
        self.assertIn("hashFiles(", restore_steps)
        self.assertIn("forgejo.sha", restore_steps)
        self.assertIn("restore-keys:", restore_steps)
        for forbidden in ("output/", "dist/", "latest.json", ".raucb", ".key", ".crt"):
            self.assertNotIn(forbidden, restore_steps)
            self.assertNotIn(forbidden, save_steps)

        for save_step, restore_id in (
                (compiler_save_step, "buildroot-compiler-cache"),
                (download_save_step, "buildroot-download-cache")):
            expected_condition = (
                "if: always() && "
                "(steps.build-release.outcome == 'success' || "
                "steps.build-release.outcome == 'failure') && "
                f"steps.{restore_id}.outputs.cache-primary-key != '' && "
                f"steps.{restore_id}.outputs.cache-hit != 'true'")
            self.assertIn(expected_condition, save_step)
            self.assertNotIn("outcome == 'skipped'", save_step)
            self.assertIn(
                f"key: ${{{{ steps.{restore_id}.outputs.cache-primary-key }}}}",
                save_step)
        self.assertNotIn("upload-artifact", workflow)

        self.assertIn('BR2_DL_DIR="$workspace/.ci-cache/buildroot-dl"', workflow)
        self.assertIn(
            'BR2_CCACHE_DIR="$workspace/.ci-cache/buildroot-ccache"', workflow)
        self.assertIn('BR2_DL_DIR BR2_CCACHE_DIR', ci_release)
        self.assertIn("ccache-stats", ci_release)
        self.assertIn("if ! make --silent", ci_release)
        self.assertIn('make -s -C "${repo_root}/buildroot" O="$release_output" distclean', release)
        self.assertIn("BR2_CCACHE=y", defconfig)
        self.assertIn("BR2_CCACHE_USE_BASEDIR=y", defconfig)
        self.assertIn("FORGEJO_TOKEN: ${{ secrets.QBT_RELEASE_KEY }}", workflow)


if __name__ == "__main__":
    unittest.main()
