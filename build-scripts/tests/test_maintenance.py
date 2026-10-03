# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import io
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SELECTOR = ROOT / "build-scripts/maintenance-select.py"
SCRIPT = ROOT / "build-scripts/maintenance-release.sh"
WORKFLOW = ROOT / ".forgejo/workflows/maintenance.yml"

spec = importlib.util.spec_from_file_location("maintenance_select", SELECTOR)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def tags(*names):
    return [f"deadbeef\trefs/tags/{name}\n" for name in names]


class MaintenanceSelectionTests(unittest.TestCase):
    def test_buildroot_numeric_final_order_and_rc_rejection(self):
        selected = selector.select("buildroot", tags(
            "2026.05.9", "2026.08-rc1", "2026.08", "2026.08.2",
            "2026.08.10", "2026.11-rc2"))
        self.assertEqual(selected, "2026.08.10")

    def test_qbittorrent_numeric_final_order_and_prerelease_rejection(self):
        selected = selector.select("qbittorrent", tags(
            "release-5.2.9", "release-5.2.10", "release-5.3.0alpha1",
            "release-5.3.0beta1", "release-5.3.0rc1"))
        self.assertEqual(selected, "release-5.2.10")

    def test_no_final_tag_fails(self):
        for kind, candidate in (("buildroot", "2026.11-rc1"),
                                ("qbittorrent", "release-5.3.0rc1")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                selector.select(kind, tags(candidate))

    def test_next_revision_numeric_and_malformed_rejection(self):
        self.assertEqual(selector.next_revision(["revision-9", "revision-10"]),
                         "revision-11")
        for bad in ("revision-0", "revision-01", "revision-x", "revsion-3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                selector.next_revision(["revision-2", bad])

    def test_selector_cli_works_with_local_fixture(self):
        result = subprocess.run(
            [sys.executable, str(SELECTOR), "qbittorrent"],
            input="".join(tags("release-5.2.2", "release-5.3.0beta1")),
            text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "release-5.2.2")


class MaintenanceContractTests(unittest.TestCase):
    def test_workflow_schedule_trust_and_concurrency(self):
        source = WORKFLOW.read_text()
        self.assertIn('cron: "17 9 * * 0"', source)
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("group: qbtos-maintenance", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn("refs/heads/main", source)
        self.assertNotIn("pull_request:", source)

    def test_validation_precedes_commit_tag_and_atomic_push(self):
        source = SCRIPT.read_text()
        self.assertLess(source.index("make check\n"), source.index("git tag \"$tag\" HEAD"))
        self.assertLess(source.index("make build\n"), source.index("git tag \"$tag\" HEAD"))
        self.assertIn("git push --atomic", source)
        self.assertIn('git push --atomic origin HEAD:refs/heads/main "refs/tags/$tag:refs/tags/$tag"', source)
        self.assertNotIn("--force", source)
        self.assertIn('OUTPUT="$validation_output" QBTOS_OUTPUT_DIR="$validation_output" make configure', source)
        self.assertIn('OUTPUT="$validation_output" QBTOS_OUTPUT_DIR="$validation_output" make build', source)
        self.assertIn("sfdisk', '--json'", source)
        self.assertIn("if test \"$changed\" -eq 0 && test \"$unreleased\" = no", source)

    def test_only_allowlisted_sources_change(self):
        source = SCRIPT.read_text()
        self.assertIn("git add -- buildroot \"$qb_mk\" \"$qb_hash\"", source)
        self.assertNotIn("git submodule update --remote", source)
        self.assertNotIn("git add -A", source)

    def test_token_not_written_to_remote_or_script(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn('printf \'%s\\n\' "$QBTOS_MAINTENANCE_TOKEN"', workflow)
        self.assertIn("vars.QBTOS_MAINTENANCE_USERNAME", workflow)
        self.assertNotIn("git remote set-url origin https://$", workflow)
        self.assertNotIn("set -x", workflow)


@unittest.skipUnless(os.name == "posix", "Git fixture uses POSIX shell")
class MaintenanceFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "buildroot-upstream"
        self.upstream.mkdir()
        self.git("init", "-q", "-b", "main", cwd=self.upstream)
        self.git("config", "user.email", "test@example.invalid", cwd=self.upstream)
        self.git("config", "user.name", "Fixture", cwd=self.upstream)
        (self.upstream / "Makefile").write_text("all:\n\t@true\n")
        self.git("add", ".", cwd=self.upstream)
        self.git("commit", "-qm", "Fixture Buildroot", cwd=self.upstream)
        self.git("tag", "2026.05.1", cwd=self.upstream)
        (self.upstream / "UPDATED").write_text("stable release\n")
        self.git("add", ".", cwd=self.upstream)
        self.git("commit", "-qm", "Next stable Buildroot", cwd=self.upstream)
        self.git("tag", "2026.08", cwd=self.upstream)
        self.remote = self.root / "remote.git"
        self.git("init", "-q", "--bare", str(self.remote), cwd=self.root)
        self.work = self.root / "work"
        self.work.mkdir()
        self.git("init", "-q", "-b", "main", cwd=self.work)
        self.git("config", "user.email", "test@example.invalid", cwd=self.work)
        self.git("config", "user.name", "Fixture", cwd=self.work)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q",
                 str(self.upstream), "buildroot", cwd=self.work)
        self.git("-C", "buildroot", "checkout", "-q", "2026.05.1", cwd=self.work)
        self.git("-C", "buildroot", "remote", "set-url", "origin",
                 "https://gitlab.com/buildroot.org/buildroot.git", cwd=self.work)
        self.git("remote", "add", "origin", str(self.remote), cwd=self.work)
        (self.work / "build-scripts/tests").mkdir(parents=True)
        for name in ("maintenance-release.sh", "maintenance-select.py", "maintenance.conf"):
            shutil.copy(ROOT / "build-scripts" / name, self.work / "build-scripts" / name)
        package = self.work / "br2-external/package/qbittorrent"
        package.mkdir(parents=True)
        (package / "0001-http-include-container-headers-for-Qt-6.8.patch").write_text(
            "legacy Qt header patch\n")
        (package / "qbittorrent.mk").write_text("QBITTORRENT_VERSION = 4.6.7\n")
        (package / "qbittorrent.hash").write_text("sha256  old  qbittorrent-4.6.7.tar.gz\nsha256  old  COPYING\n")
        config = self.work / "br2-external/configs"
        config.mkdir(parents=True)
        for name in ("qbtos_rpi4_defconfig", "qbtos_qemu_amd64_defconfig",
                     "qbtos_qemu_arm64_defconfig"):
            (config / name).write_text("BR2_TOOLCHAIN_EXTERNAL_CXX=y\nBR2_PACKAGE_QBITTORRENT=y\n")
        (self.work / ".gitignore").write_text("/output/\n")
        (self.work / "unrelated.txt").write_text("original\n")
        self.git("add", ".", cwd=self.work)
        self.git("commit", "-qm", "Fixture source", cwd=self.work)
        self.git("tag", "revision-1", cwd=self.work)
        self.git("push", "-q", "origin", "main", "revision-1", cwd=self.work)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.wrapper("git", """#!/bin/sh
if [ "$1" = push ] && [ "$2" = --atomic ] &&
   [ "${QBTOS_FIXTURE_FAIL_PUSH:-0}" = 1 ]; then
  exit 9
fi
if [ "$1" = -C ] && [ "$2" = buildroot ] && [ "$3" = fetch ] &&
   [ "${QBTOS_FIXTURE_BUILDROOT_UPDATE:-0}" = 1 ]; then
  exec /usr/bin/git -C buildroot -c protocol.file.allow=always fetch --no-tags "$QBTOS_FIXTURE_BUILDROOT_REPO" "$6"
fi
if [ "$1" = ls-remote ] && [ "$2" = --tags ] && [ "$3" = --refs ]; then
  case "$4" in
    https://gitlab.com/buildroot.org/buildroot.git)
      printf 'abc\\trefs/tags/2026.05.1\\n'
      if [ "${QBTOS_FIXTURE_BUILDROOT_UPDATE:-0}" = 1 ]; then
        printf 'abc\\trefs/tags/2026.08\\n'
      fi
      exit 0 ;;
    https://github.com/qbittorrent/qBittorrent.git)
      printf 'abc\\trefs/tags/release-4.6.7\\n'
      if [ "${QBTOS_FIXTURE_UPDATE:-0}" = 1 ]; then
        printf 'abc\\trefs/tags/release-4.6.8\\n'
      fi
      exit 0 ;;
  esac
fi
exec /usr/bin/git "$@"
""")
        self.wrapper("curl", """#!/bin/sh
previous=
for arg do
  if [ "$previous" = --output ]; then cp "$QBTOS_FIXTURE_ARCHIVE" "$arg"; exit 0; fi
  previous=$arg
done
exit 2
""")
        self.wrapper("sfdisk", """#!/bin/sh
test "$1" = --json || exit 2
cat <<'JSON'
{"partitiontable":{"label":"dos","id":"0x5142544f","partitions":[
  {"type":"c","start":2048,"size":131072,"bootable":true},
  {"type":"83","start":133120,"size":196608},
  {"type":"83","start":329728,"size":196608},
  {"type":"f","start":526336,"size":1050624},
  {"type":"83","start":528384,"size":1048576}
]}}
JSON
""")
        self.wrapper("make", """#!/bin/sh
case "$1" in
  check)
    [ "${QBTOS_FIXTURE_FAIL_CHECK:-0}" = 0 ] || exit 7
    if [ "${QBTOS_FIXTURE_RACE:-0}" = 1 ]; then
      /usr/bin/git clone -q "$QBTOS_FIXTURE_REMOTE" "$QBTOS_FIXTURE_RACER"
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" checkout -q main
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" config user.email race@example.invalid
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" config user.name Race
      printf race > "$QBTOS_FIXTURE_RACER/race.txt"
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" add race.txt
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" commit -qm 'Concurrent change'
      /usr/bin/git -C "$QBTOS_FIXTURE_RACER" push -q origin main
    fi ;;
  configure)
    mkdir -p "$QBTOS_OUTPUT_DIR"
    if [ "${QBTOS_FIXTURE_BUILDROOT_UPDATE:-0}" = 1 ]; then
      sed 's/BR2_TOOLCHAIN_EXTERNAL_CXX=y/BR2_INSTALL_LIBSTDCPP=y/' \
        br2-external/configs/qbtos_rpi4_defconfig > "$QBTOS_OUTPUT_DIR/.config"
    else
      cp br2-external/configs/qbtos_rpi4_defconfig "$QBTOS_OUTPUT_DIR/.config"
    fi ;;
  build)
    mkdir -p "$QBTOS_OUTPUT_DIR/images" "$QBTOS_OUTPUT_DIR/target/usr/bin" "$QBTOS_OUTPUT_DIR/target/etc/rauc"
    printf x > "$QBTOS_OUTPUT_DIR/images/rootfs.squashfs"
    printf x > "$QBTOS_OUTPUT_DIR/images/sdcard.img"
    printf x > "$QBTOS_OUTPUT_DIR/target/usr/bin/qbittorrent-nox"
    printf x > "$QBTOS_OUTPUT_DIR/target/usr/bin/rauc"
    chmod +x "$QBTOS_OUTPUT_DIR/target/usr/bin/qbittorrent-nox" "$QBTOS_OUTPUT_DIR/target/usr/bin/rauc"
    printf x > "$QBTOS_OUTPUT_DIR/target/etc/rauc/keyring.pem"
    if [ "${QBTOS_FIXTURE_PRIVATE_KEY:-0}" = 1 ]; then
      printf '%s\\n' '-----BEGIN PRIVATE KEY-----' > "$QBTOS_OUTPUT_DIR/target/etc/rauc/leak.pem"
    fi
    if [ "${QBTOS_FIXTURE_CONCURRENT_EDIT:-0}" = 1 ]; then
      printf 'user edit\\n' >> unrelated.txt
    fi ;;
  *) exit 2 ;;
esac
""")
        self.archive = self.root / "qb.tar.gz"
        with tarfile.open(self.archive, "w:gz") as tar:
            data = b"GPL fixture\n"
            member = tarfile.TarInfo("qBittorrent-release-4.6.8/COPYING")
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
            header = b"#include <QHash>\n#include <QMap>\n"
            member = tarfile.TarInfo("qBittorrent-release-4.6.8/src/base/http/types.h")
            member.size = len(header)
            tar.addfile(member, io.BytesIO(header))

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def wrapper(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def run_maintenance(self, update=False, buildroot_update=False,
                        fail_check=False, race=False, private_key=False,
                        fail_push=False, concurrent_edit=False, publish=False):
        env = os.environ.copy()
        env.update(PATH=f"{self.bin}:{env['PATH']}", QBTOS_FIXTURE_UPDATE=str(int(update)),
                   QBTOS_FIXTURE_BUILDROOT_UPDATE=str(int(buildroot_update)),
                   QBTOS_FIXTURE_BUILDROOT_REPO=str(self.upstream),
                   QBTOS_FIXTURE_FAIL_CHECK=str(int(fail_check)),
                   QBTOS_FIXTURE_RACE=str(int(race)),
                   QBTOS_FIXTURE_PRIVATE_KEY=str(int(private_key)),
                   QBTOS_FIXTURE_FAIL_PUSH=str(int(fail_push)),
                   QBTOS_FIXTURE_CONCURRENT_EDIT=str(int(concurrent_edit)),
                   QBTOS_FIXTURE_REMOTE=str(self.remote),
                   QBTOS_FIXTURE_RACER=str(self.root / "racer"),
                   QBTOS_FIXTURE_ARCHIVE=str(self.archive))
        return subprocess.run(["sh", "build-scripts/maintenance-release.sh",
                               *(["--publish"] if publish else [])], cwd=self.work,
                              env=env, capture_output=True, text=True)

    def test_noop_does_not_commit_or_tag(self):
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Publication: no-op", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))

    def test_successful_candidate_is_hashed_validated_and_published(self):
        result = self.run_maintenance(update=True, publish=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("qBittorrent: 4.6.7 -> 4.6.8", result.stdout)
        self.assertIn("Validation: passed", result.stdout)
        self.assertIn("Revision: revision-2", result.stdout)
        self.assertEqual(self.git("rev-parse", "revision-2", cwd=self.work),
                         self.git("rev-parse", "HEAD", cwd=self.work))
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main", cwd=self.root),
                         self.git("rev-parse", "HEAD", cwd=self.work))
        self.assertIn("qbittorrent-4.6.8.tar.gz", (self.work / "br2-external/package/qbittorrent/qbittorrent.hash").read_text())
        hashes = (self.work / "br2-external/package/qbittorrent/qbittorrent.hash").read_text()
        self.assertIn(hashlib.sha256(self.archive.read_bytes()).hexdigest(), hashes)
        self.assertIn(hashlib.sha256(b"GPL fixture\n").hexdigest(), hashes)
        self.assertFalse((self.work / "br2-external/package/qbittorrent/0001-http-include-container-headers-for-Qt-6.8.patch").exists())

    def test_local_preview_keeps_candidate_without_publishing(self):
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance(update=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("preview only", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))
        self.assertIn("qbittorrent.mk", self.git("status", "--short", cwd=self.work))

    def test_failed_validation_leaves_remote_and_tags_untouched(self):
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance(update=True, fail_check=True, publish=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed at make check", result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main", cwd=self.root), before)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))
        self.assertEqual(self.git("status", "--porcelain", cwd=self.work), "")
        self.assertTrue((self.work / "br2-external/package/qbittorrent/0001-http-include-container-headers-for-Qt-6.8.patch").exists())

    def test_buildroot_candidate_updates_only_approved_submodule(self):
        result = self.run_maintenance(buildroot_update=True, publish=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Buildroot: 2026.05.1 -> 2026.08", result.stdout)
        self.assertEqual(self.git("-C", "buildroot", "describe", "--tags", "--exact-match", cwd=self.work),
                         "2026.08")
        changed = self.git("show", "--format=", "--name-only", "HEAD", cwd=self.work)
        self.assertIn("buildroot", changed)
        for config in (self.work / "br2-external/configs").glob("qbtos_*_defconfig"):
            self.assertNotIn("BR2_TOOLCHAIN_EXTERNAL_CXX", config.read_text())

    def test_dirty_checkout_is_rejected(self):
        (self.work / "untracked.txt").write_text("dirty\n")
        result = self.run_maintenance(update=True, publish=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Working tree must be clean", result.stdout + result.stderr)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))

    def test_existing_unreleased_commit_is_validated_without_empty_commit(self):
        (self.work / "feature.txt").write_text("release me\n")
        self.git("add", "feature.txt", cwd=self.work)
        self.git("commit", "-qm", "Add fixture feature", cwd=self.work)
        self.git("push", "-q", "origin", "main", cwd=self.work)
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance(publish=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Existing unreleased qbtOS commits: yes", result.stdout)
        self.assertIn("Maintenance commit: none", result.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertEqual(self.git("rev-parse", "revision-2", cwd=self.work), before)

    def test_remote_main_race_aborts_publication(self):
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance(update=True, race=True, publish=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin/main advanced during validation", result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))
        self.assertEqual(self.git("status", "--porcelain", cwd=self.work), "")

    def test_private_key_in_image_aborts_before_tag(self):
        result = self.run_maintenance(update=True, private_key=True, publish=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PEM private key material entered the image", result.stdout + result.stderr)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))

    def test_failed_push_restores_candidate_but_preserves_unrelated_edit(self):
        before = self.git("rev-parse", "HEAD", cwd=self.work)
        result = self.run_maintenance(update=True, fail_push=True,
                                      concurrent_edit=True, publish=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed at atomically push", result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work), before)
        self.assertNotIn("revision-2", self.git("tag", "--list", cwd=self.work))
        self.assertEqual((self.work / "unrelated.txt").read_text(),
                         "original\nuser edit\n")
        self.assertNotIn("qbittorrent.mk", self.git("status", "--short", cwd=self.work))

    def test_emergency_holds_are_reported_and_do_not_upgrade(self):
        config = self.work / "build-scripts/maintenance.conf"
        config.write_text("BUILDROOT_HOLD=2026.05.1\nQBITTORRENT_HOLD=4.6.7\n")
        self.git("add", "build-scripts/maintenance.conf", cwd=self.work)
        self.git("commit", "-qm", "Hold upstreams", cwd=self.work)
        self.git("tag", "revision-2", cwd=self.work)
        self.git("push", "-q", "origin", "main", "revision-2", cwd=self.work)
        result = self.run_maintenance(update=True, buildroot_update=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Buildroot: held at 2026.05.1", result.stdout)
        self.assertIn("qBittorrent: held at 4.6.7", result.stdout)
        self.assertIn("Publication: no-op", result.stdout)


if __name__ == "__main__":
    unittest.main()
