"""Pacotes e releases usam apenas código versionado e preservam dados privados."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import warnings
from zipfile import ZipFile, ZipInfo


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "deploy_release.py"
SPEC = importlib.util.spec_from_file_location("lumi_deploy_test", SOURCE)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)

COMMIT = "a" * 40
RELEASE_ID = "gha-" + COMMIT[:12] + "-1-1"
REQUIRED = {
    "app/main.py": b"# application fixture\n",
    "app/whatsapp/webhook.py": b"# webhook fixture\n",
    "web/console.html": b"<html>fixture</html>\n",
    "requirements.txt": b"example-package==1.0\n",
    "requirements-vm.lock": b"example-package==1.0\n",
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


class DeployReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lumi-deploy-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "installation"
        previous = self.root / "releases" / "previous"
        previous.mkdir(parents=True)
        for name, content in REQUIRED.items():
            path = previous / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.root / "current").symlink_to(previous, target_is_directory=True)
        for name in ["private/settings.env", "data/store.db", "logs/old.log"]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private fixture, never package or overwrite\n")
        self.previous = previous
        self.before = self.snapshot()

    def snapshot(self):
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for folder in ["private", "data", "logs", "releases/previous"]
            for p in (self.root / folder).rglob("*")
            if p.is_file()
        }

    def assert_preserved(self):
        self.assertEqual(self.snapshot(), self.before)
        self.assertTrue((self.root / "current").is_symlink())
        self.assertEqual((self.root / "current").resolve(), self.previous.resolve())

    def archive(self, overrides=None, remove=(), extra=None, duplicate=None,
                link=None, metadata=None, manifest_update=None):
        files = dict(REQUIRED)
        files.update(overrides or {})
        for name in remove:
            files.pop(name)
        files["deployment.json"] = json.dumps(
            metadata or {"commit": COMMIT, "branch": "develop"}
        ).encode()
        manifest = {name: digest(content) for name, content in files.items()}
        if manifest_update:
            manifest_update(manifest)
        files["release-manifest.json"] = json.dumps(manifest).encode()
        path = self.base / "release.zip"
        with warnings.catch_warnings(), ZipFile(path, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in files.items():
                archive.writestr(name, content)
            for name, content in (extra or {}).items():
                archive.writestr(name, content)
            if duplicate:
                archive.writestr(duplicate, files[duplicate])
            if link:
                info = ZipInfo(link)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "../private/settings.env")
        return path

    def prepare(self, archive, **kwargs):
        params = dict(
            root=self.root, archive=archive,
            expected_hash=digest(archive.read_bytes()), commit=COMMIT,
            branch="develop", release_id=RELEASE_ID,
        )
        params.update(kwargs)
        return deploy.prepare_release(**params)

    def rejected(self, archive, **kwargs):
        with self.assertRaises((ValueError, RuntimeError)):
            self.prepare(archive, **kwargs)
        self.assert_preserved()
        self.assertFalse((self.root / "releases" / RELEASE_ID).exists())

    def test_allowed_paths_exclude_private_files_and_ambiguous_windows_paths(self):
        for name in [*REQUIRED, "services/example.py", "demo/tenants.json",
                     "docs/privacy-policy.html", "docs/privacy-policy-draft.html",
                     "scripts/deploy_release.py", "scripts/windows/deploy-release.ps1"]:
            with self.subTest(allowed=name):
                self.assertTrue(deploy.allowed_path(name))
        for name in ["../private/settings.env", "/app/main.py", "app/../private/x.py",
                     "app\\main.py", "app/main.py:secret", "C:/app/main.py",
                     "app/.env", "app/settings.env", "app/cache.db", "web/token.key",
                     "services/backup.dump", "app/__pycache__/main.pyc",
                     "app/CON.py", "app/aux.txt", "app/LPT1/file.py",
                     "app/foo./bar.py", "app/main.py ",
                     "private/settings.env", ".data/release.zip", "tests/test_app.py"]:
            with self.subTest(rejected=name):
                self.assertFalse(deploy.allowed_path(name))

    def test_valid_release_is_prepared_without_activating_or_mutating_private_state(self):
        archive = self.archive()
        release = self.prepare(archive)
        self.assertEqual(release, self.root / "releases" / RELEASE_ID)
        for name, content in REQUIRED.items():
            self.assertEqual((release / name).read_bytes(), content)
        self.assert_preserved()

    def test_repeated_release_never_overwrites_existing_directory(self):
        archive = self.archive()
        release = self.prepare(archive)
        marker = release / "operator-marker"
        marker.write_text("preserve")
        with self.assertRaises((ValueError, RuntimeError)):
            self.prepare(archive)
        self.assertEqual(marker.read_text(), "preserve")
        self.assert_preserved()

    def test_wrong_archive_digest_is_rejected_before_extraction(self):
        self.rejected(self.archive(), expected_hash="0" * 64)

    def test_wrong_metadata_and_unsupported_branches_are_rejected(self):
        for metadata in [
            {"commit": "b" * 40, "branch": "develop"},
            {"commit": COMMIT, "branch": "main"},
            {"commit": COMMIT, "branch": "feature/test"},
            {"branch": "develop"},
        ]:
            with self.subTest(metadata=metadata):
                self.rejected(self.archive(metadata=metadata))
        self.rejected(self.archive(), branch="feature/test")

    def test_invalid_release_ids_cannot_escape_or_overwrite_another_release(self):
        for release_id in ["../private", "previous", "gha-" + "b" * 12 + "-1-1",
                           RELEASE_ID + "/nested", RELEASE_ID + ":stream"]:
            with self.subTest(release_id=release_id):
                self.rejected(self.archive(), release_id=release_id)

    def test_missing_required_files_and_manifest_members_are_rejected(self):
        for name in REQUIRED:
            with self.subTest(missing=name):
                self.rejected(self.archive(remove=[name]))
        self.rejected(self.archive(manifest_update=lambda m: m.pop("deployment.json")))
        self.rejected(self.archive(manifest_update=lambda m: m.update({"app/missing.py": "0" * 64})))

    def test_modified_file_and_unmanifested_file_are_rejected(self):
        self.rejected(self.archive(manifest_update=lambda m: m.update({"app/main.py": "0" * 64})))
        self.rejected(self.archive(extra={"app/unlisted.py": b"unlisted"}))

    def test_duplicate_zip_entries_and_symbolic_links_are_rejected(self):
        self.rejected(self.archive(duplicate="app/main.py"))
        self.rejected(self.archive(link="app/link.py"))

    def test_traversal_and_private_files_are_rejected_even_when_manifested(self):
        for name in ["../private/settings.env", "app/../../outside.py",
                     "app\\..\\private.py", "app/main.py:secret", "app/.env",
                     "app/CON.py", "app/foo./bar.py", "app/main.py "]:
            with self.subTest(name=name):
                self.rejected(self.archive(overrides={name: b"unexpected"}))
        self.assertFalse((self.base / "outside.py").exists())

    def test_dependency_changes_require_separate_environment_upgrade(self):
        for name in ["requirements.txt", "requirements-vm.lock"]:
            with self.subTest(name=name):
                self.rejected(self.archive(overrides={name: b"example-package==2.0\n"}))

    def test_package_reads_committed_files_and_excludes_dirty_untracked_and_private_files(self):
        repo = self.base / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE).decode().strip()

        git("init", "-q")
        git("config", "user.name", "Deploy Test")
        git("config", "user.email", "deploy@example.test")
        tracked = dict(REQUIRED)
        tracked.update({"tests/not-runtime.py": b"test fixture", "app/.env": b"FICTITIOUS=fixture"})
        for name, content in tracked.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        git("add", ".")
        git("commit", "-qm", "fixture")
        commit = git("rev-parse", "HEAD")
        (repo / "app/main.py").write_bytes(b"dirty code must not deploy")
        (repo / "app/untracked.py").write_bytes(b"untracked code must not deploy")
        output = self.base / "built.zip"
        result = deploy.build_package(repo, output, commit, "develop")
        self.assertEqual(result["sha256"], digest(output.read_bytes()))
        with ZipFile(output) as archive:
            self.assertEqual(archive.read("app/main.py"), REQUIRED["app/main.py"])
            for name in ["app/untracked.py", "app/.env", "tests/not-runtime.py"]:
                self.assertNotIn(name, archive.namelist())
            metadata = json.loads(archive.read("deployment.json"))
            self.assertEqual(metadata["commit"], commit)
            self.assertEqual(metadata["branch"], "develop")
            manifest = json.loads(archive.read("release-manifest.json"))
            self.assertEqual(set(manifest), set(archive.namelist()) - {"release-manifest.json"})
            for name, expected in manifest.items():
                self.assertEqual(digest(archive.read(name)), expected)


if __name__ == "__main__":
    unittest.main()
