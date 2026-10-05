"""No network calls: exercise the complete one-time publication state machine."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

import build_identity as identity
import ci_quality_checks
import publish_game_build as publish


def environment(number=10, run_id=1000):
    return {"GITHUB_REPOSITORY": "RHS059/rust_duty", "GITHUB_RUN_NUMBER": str(number),
            "GITHUB_RUN_ID": str(run_id), "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
            "GITHUB_REF_NAME": "aella/automatic-game-updates-r1",
            "GITHUB_REF": "refs/heads/aella/automatic-game-updates-r1",
            "GITHUB_EVENT_NAME": "push", "RUST_DUTY_BUILD_VERSION": "0.1.7",
            "RUST_DUTY_BUILD_RESULT": "success"}


class FakeGitHub:
    def __init__(self):
        self.releases = {}
        self.tags = {}
        self.latest = None
        self.contents = {}
        self.uploads = []
        self.writes = []
        self.next_asset = 1
        self.interrupt_after = None

    def api(self, endpoint, *, payload=None, missing_ok=False):
        if payload is not None:
            self.writes.append((endpoint, copy.deepcopy(payload)))
            if endpoint == "releases":
                release = {**payload, "id": len(self.releases) + 1, "assets": [],
                           "html_url": f'https://github.com/RHS059/rust_duty/releases/tag/{payload["tag_name"]}'}
                self.releases[release["id"]] = release
            else:
                release = self.releases[int(endpoint.split("/")[-1])]
                release.update(payload)
                if payload.get("draft") is False:
                    self.tags[release["tag_name"]] = release["target_commitish"]
                    if payload.get("make_latest") == "true":
                        self.latest = release["id"]
            return copy.deepcopy(release)
        if endpoint == "releases/latest":
            value = self.releases.get(self.latest)
        elif endpoint.startswith("releases/tags/"):
            value = next((r for r in self.releases.values() if r["tag_name"] == endpoint[14:]), None)
        elif endpoint.startswith("git/ref/tags/"):
            sha = self.tags.get(endpoint[13:])
            value = None if sha is None else {"object": {"type": "commit", "sha": sha}}
        else:
            value = self.releases.get(int(endpoint.split("/")[-1]))
        if value is None and not missing_ok:
            raise RuntimeError("HTTP 404")
        return copy.deepcopy(value)

    def upload(self, tag, path):
        if self.interrupt_after is not None and len(self.uploads) >= self.interrupt_after:
            raise RuntimeError("simulated interrupted upload")
        release = next(r for r in self.releases.values() if r["tag_name"] == tag)
        if any(a["name"] == path.name for a in release["assets"]):
            raise ValueError("duplicate asset upload")
        self.add_asset(release, path.name, path.read_bytes())
        self.uploads.append(path.name)

    def add_asset(self, release, name, content):
        number = self.next_asset
        self.next_asset += 1
        self.contents[number] = content
        record = {"id": number, "name": name, "size": len(content), "state": "uploaded",
                  "digest": "sha256:" + hashlib.sha256(content).hexdigest()}
        release["assets"].append(record)
        return record

    def download(self, asset, destination):
        Path(destination).write_bytes(self.contents[asset["id"]])


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        # Preserve regression coverage of the frozen historical publisher.
        patch = mock.patch.object(identity, "package_version", return_value="0.1.7")
        patch.start()
        self.addCleanup(patch.stop)

    def test_one_time_version_and_sequence_do_not_increment_for_draft_pushes(self):
        item = identity.context(environment(), publication=True)
        self.assertEqual(item["version"], "0.1.7")
        self.assertEqual(item["sequence"], 5)
        self.assertEqual(item["source"]["commit"], "a" * 40)
        self.assertEqual(identity.context(environment(11, 1002))["version"], "0.1.7")

    def test_fail_closed_event_repository_branch_version_and_matrix_result(self):
        for key, value in [("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_EVENT_NAME", "workflow_dispatch"),
                           ("GITHUB_REPOSITORY", "someone/fork"), ("GITHUB_REF_NAME", "main"),
                           ("GITHUB_REF", "refs/pull/1/merge"), ("RUST_DUTY_BUILD_RESULT", "failure"),
                           ("RUST_DUTY_BUILD_RESULT", "cancelled"), ("RUST_DUTY_BUILD_RESULT", "skipped"),
                           ("RUST_DUTY_BUILD_VERSION", "0.1.4"), ("RUST_DUTY_BUILD_VERSION", None),
                           ("GITHUB_SHA", "main"),
                           ("GITHUB_RUN_NUMBER", "01"), ("GITHUB_RUN_ID", "0"),
                           ("GITHUB_RUN_NUMBER", str(2**64))]:
            env = environment()
            env[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                identity.context(env, publication=True)
        env = environment()
        env["GITHUB_REF_NAME"] = "aella/layered-locomotion-integration-r1"
        env["GITHUB_REF"] = "refs/heads/" + env["GITHUB_REF_NAME"]
        with self.assertRaises(ValueError):
            identity.context(env, publication=True)

    def test_stamp_executes_no_gui_version_and_verifies_hash(self):
        for platform, (_, executable, _, magic) in identity.TARGETS.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / executable
                binary.write_bytes(magic + b"native fixture")
                with mock.patch.object(identity.subprocess, "check_output", side_effect=["0.1.7\n", "0.1.7+build.1000.1\n"]) as run:
                    identity.stamp(root, platform, environment())
                self.assertEqual(run.call_args_list[0].args[0], [str(binary.resolve()), "--build-version"])
                self.assertEqual(run.call_args_list[1].args[0], [str(binary.resolve()), "--build-label"])
                identity.verify(root, platform, identity.context(environment()))
                binary.write_bytes(magic + b"changed fixture")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    identity.verify(root, platform, identity.context(environment()))

    def test_wrong_embedded_version_does_not_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vector-range").write_bytes(b"\x7fELFold build")
            with mock.patch.object(identity.subprocess, "check_output", return_value="0.1.4\n"):
                with self.assertRaisesRegex(ValueError, "embedded game version"):
                    identity.stamp(root, "linux", environment())
            self.assertFalse((root / identity.IDENTITY_FILE).exists())


class CandidateIdentityTests(unittest.TestCase):
    @staticmethod
    def environment():
        env = environment()
        env.pop("RUST_DUTY_BUILD_VERSION")
        env["GITHUB_REF_NAME"] = "aella/content-delta-followup-r1"
        env["GITHUB_REF"] = "refs/heads/" + env["GITHUB_REF_NAME"]
        return env

    def test_checked_out_package_and_lock_match_candidate(self):
        self.assertEqual(identity.package_version(), "0.1.11")
        with (Path(__file__).resolve().parents[1] / "Cargo.lock").open("rb") as stream:
            lock = identity.tomllib.load(stream)
        game = [p for p in lock["package"] if p["name"] == "vector-range"]
        self.assertEqual([p["version"] for p in game], [identity.package_version()])
        item = identity.context(self.environment())
        self.assertEqual((item["version"], item["sequence"]), ("0.1.11", 11))
        env = self.environment()
        env["GITHUB_RUN_NUMBER"] = "11"
        env["GITHUB_RUN_ID"] = "1002"
        self.assertEqual(identity.context(env)["version"], item["version"])
        self.assertEqual(identity.context(env)["sequence"], item["sequence"])

    def test_candidate_rejects_stale_pins_and_legacy_publication(self):
        env = self.environment()
        env["RUST_DUTY_BUILD_VERSION"] = "0.1.11"
        self.assertEqual(identity.context(env)["version"], "0.1.11")
        for version in ("0.1.5", "0.1.7", "0.1.8", "0.1.9", "0.1.10"):
            env["RUST_DUTY_BUILD_VERSION"] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "Cargo package"):
                identity.context(env)
        for branch in ("aella/content-delta-followup-r1", *identity.RELEASE_BRANCHES):
            env = self.environment()
            env["GITHUB_REF_NAME"] = branch
            env["GITHUB_REF"] = "refs/heads/" + branch
            with self.subTest(branch=branch), self.assertRaisesRegex(ValueError, "publication requires"):
                identity.context(env, publication=True)

    def test_candidate_stamps_and_verifies_both_platforms(self):
        for platform, (_, executable, _, magic) in identity.TARGETS.items():
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / executable).write_bytes(magic + b"candidate native fixture")
                with mock.patch.object(identity.subprocess, "check_output", side_effect=["0.1.11\n", "0.1.11+build.1000.1\n"]):
                    stamped = identity.stamp(root, platform, self.environment())
                self.assertEqual(stamped["schema"], "rust-duty-build-identity/v1")
                self.assertEqual((stamped["version"], stamped["sequence"]), ("0.1.11", 11))
                identity.verify(root, platform, identity.context(self.environment()))

    def test_previous_binary_cannot_receive_candidate_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vector-range").write_bytes(b"\x7fELFold build")
            for version in ("0.1.7", "0.1.8", "0.1.9", "0.1.10"):
                with self.subTest(version=version), mock.patch.object(
                    identity.subprocess, "check_output", return_value=version + "\n"
                ):
                    with self.assertRaisesRegex(ValueError, "embedded game version"):
                        identity.stamp(root, "linux", self.environment())
                self.assertFalse((root / identity.IDENTITY_FILE).exists())


class PublicationTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(identity, "package_version", return_value="0.1.7")
        patch.start()
        self.addCleanup(patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tested = self.root / "tested"
        self.output = self.root / "release"
        self.identity = identity.context(environment(), publication=True)
        self.github = FakeGitHub()
        for platform, (_, executable, _, magic) in publish.DELIVERY_TARGETS.items():
            source = self.tested / platform
            source.mkdir(parents=True)
            (source / executable).write_bytes(magic + b"native fixture")
            with mock.patch.object(identity.subprocess, "check_output", side_effect=["0.1.7\n", "0.1.7+build.1000.1\n"]):
                identity.stamp(source, platform, environment())
        with mock.patch.object(publish.package_game, "stage", side_effect=self.fixture_stage) as stage:
            self.provenance = publish.prepare(self.tested, self.output, self.identity)
        self.assertEqual(stage.call_count, 2)
        self.assertTrue(all(call.kwargs["require_generated"] for call in stage.call_args_list))
        self.assertEqual(sum(call.kwargs.get("update", False) for call in stage.call_args_list), 1)

    @staticmethod
    def fixture_stage(source, executable, output, update=False, require_generated=False):
        output.mkdir(parents=True)
        shutil.copy2(source / executable, output / executable)
        assets = output / "assets/reload"
        assets.mkdir(parents=True)
        for name in ("asset.vra", "asset.vrs", "asset.vrm"):
            (assets / name).write_bytes(b"fixture public companion " + name.encode())
        (output / "LICENSE").write_text("license fixture")
        if not update:
            (output / "settings.cfg").write_text("fresh-install defaults")

    def publish(self):
        return publish.publish(self.github, self.output, self.identity)

    def add_baseline(self, version="0.1.3", sequence=4):
        release = self.github.api("releases", payload={"tag_name": "v" + version, "draft": True,
                                                       "prerelease": False, "target_commitish": "b" * 40})
        actual = self.github.releases[release["id"]]
        for target, executable, _, _ in publish.DELIVERY_TARGETS.values():
            bundle = b"legacy bundle"
            name = f"rust-duty-{version}-{target}.rdb"
            self.github.add_asset(actual, name, bundle)
            manifest = {"schema": 1, "repository": identity.REPOSITORY, "version": version,
                        "sequence": sequence, "target": target, "entrypoint": executable,
                        "bundle": {"name": name, "size": len(bundle), "sha256": hashlib.sha256(bundle).hexdigest()},
                        "deltas": []}
            self.github.add_asset(actual, f"update-{target}.json", json.dumps(manifest).encode())
        self.github.api(f'releases/{actual["id"]}', payload={"draft": False, "make_latest": "true"})
        self.github.writes.clear()
        return actual

    def test_complete_assets_provenance_determinism_and_user_data_exclusion(self):
        self.assertEqual(len(list(self.output.iterdir())), 5)
        self.assertEqual(self.provenance["source"], self.identity["source"])
        for platform, (target, executable, label, _) in publish.DELIVERY_TARGETS.items():
            manifest = json.loads((self.output / f"update-{target}.json").read_text())
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(manifest["version"], "0.1.7")
            self.assertEqual(manifest["sequence"], 5)
            self.assertEqual(manifest["deltas"], [])
            bundle = (self.output / manifest["bundle"]["name"]).read_bytes()
            self.assertIn(b"assets/reload/asset.vra", bundle)
            self.assertNotIn(b"settings.cfg", bundle)
            with zipfile.ZipFile(self.output / f"Rust-Duty-0.1.7-{label}-x64.zip") as archive:
                self.assertIn("settings.cfg", archive.namelist())
                self.assertEqual(archive.getinfo(executable).external_attr >> 16, 0o100755)
        again = self.root / "again"
        with mock.patch.object(publish.package_game, "stage", side_effect=self.fixture_stage):
            publish.prepare(self.tested, again, self.identity)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (again / path.name).read_bytes(), path.name)

    def test_wrong_source_artifact_and_missing_generated_assets_fail_closed(self):
        (self.tested / "windows/vector-range.exe").write_bytes(b"MZwrong run")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            publish.prepare(self.tested, self.root / "bad", self.identity)
        self.assertFalse((self.root / "bad").exists())
        with self.assertRaises(ValueError):
            publish.package_game.stage(self.tested / "windows", "vector-range.exe",
                                       self.root / "bad-payload", update=True, require_generated=True)

    def test_artifact_identity_cannot_be_reused_from_a_different_source_run(self):
        path = self.tested / "windows" / identity.IDENTITY_FILE
        data = json.loads(path.read_text())
        data["source"]["run_id"] += 1
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "source run"):
            publish.prepare(self.tested, self.root / "wrong-run", self.identity)
        self.assertFalse((self.root / "wrong-run").exists())

    def test_second_branch_push_cannot_reuse_the_one_time_public_version(self):
        self.publish()
        before = copy.deepcopy(self.github.writes)
        different = copy.deepcopy(self.identity)
        different["source"]["commit"] = "b" * 40
        different["source"]["run_id"] += 1
        with self.assertRaisesRegex(ValueError, "exact source"):
            publish.publish(self.github, self.output, different)
        self.assertEqual(self.github.writes, before)

    def test_publish_old_client_compatible_manifests_then_exact_retry_no_mutation(self):
        self.add_baseline()
        self.assertEqual(self.publish()["status"], "published")
        self.assertEqual(len(self.github.uploads), 5)
        self.assertEqual(publish.latest_identity(self.github), {"version": "0.1.7", "sequence": 5})
        self.assertTrue(all(r.get("draft") is False for r in self.github.releases.values()))
        before = copy.deepcopy(self.github.writes)
        self.assertEqual(self.publish()["status"], "already-published")
        self.assertEqual(self.github.writes, before)
        self.assertEqual(len(self.github.uploads), 5)

    def test_interrupted_draft_resumes_only_missing_assets(self):
        self.add_baseline()
        self.github.interrupt_after = 3
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.publish()
        self.assertEqual(self.github.releases[2]["draft"], True)
        self.assertEqual(publish.latest_identity(self.github)["version"], "0.1.3")
        self.github.interrupt_after = None
        self.assertEqual(self.publish()["status"], "published")
        self.assertEqual(len(self.github.uploads), 5)
        self.assertEqual(len(set(self.github.uploads)), 5)

    def test_out_of_order_older_run_cannot_regress_latest(self):
        self.add_baseline("0.1.8", 6)
        self.assertEqual(self.publish()["status"], "superseded")
        self.assertFalse(self.github.writes)
        self.assertFalse(self.github.uploads)

    def test_sequence_version_conflicts_fail_closed(self):
        for version, sequence in [("0.1.8", 4), ("0.1.6", 6), ("0.1.7", 4), ("0.1.4", 5)]:
            with self.subTest(version=version, sequence=sequence), self.assertRaises(ValueError):
                publish.publication_order(self.identity, {"version": version, "sequence": sequence})

    def test_missing_windows_bundle_fails_closed(self):
        baseline = self.add_baseline()
        baseline['assets'] = [a for a in baseline['assets'] if not a['name'].endswith('.rdb')]
        with self.assertRaisesRegex(ValueError, 'lacks complete update bundle'):
            self.publish()
        self.assertFalse(self.github.writes)

    def test_missing_linux_never_blocks_windows_and_old_assets_are_untouched(self):
        baseline = self.add_baseline()
        historical = self.github.add_asset(baseline, 'vector-range-linux-x64', b'historical Linux')
        before = copy.deepcopy(historical)
        self.assertEqual(self.publish()['status'], 'published')
        self.assertEqual(historical, before)
        self.assertEqual(self.github.contents[historical['id']], b'historical Linux')
        self.assertFalse(any('linux' in name.lower() for name in self.github.uploads))
        self.assertEqual(set(self.provenance['artifacts']), {'windows'})

    def test_existing_tag_on_other_commit_is_never_repointed(self):
        self.github.tags["v0.1.7"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "exact source"):
            self.publish()
        self.assertFalse(self.github.writes)

    def test_conflicting_existing_asset_is_never_overwritten(self):
        self.github.interrupt_after = 1
        with self.assertRaises(RuntimeError):
            self.publish()
        self.github.releases[1]["assets"][0]["digest"] = "sha256:" + "0" * 64
        self.github.interrupt_after = None
        with self.assertRaisesRegex(ValueError, "digest differs"):
            self.publish()
        self.assertEqual(len(self.github.uploads), 1)
        self.assertTrue(self.github.releases[1]["draft"])

    def test_no_digest_falls_back_to_byte_hash_verification(self):
        self.publish()
        for asset in self.github.releases[1]["assets"]:
            asset.pop("digest")
        self.assertEqual(self.publish()["status"], "already-published")
        asset = self.github.releases[1]["assets"][-1]
        self.github.contents[asset["id"]] = b"corrupt content"
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.publish()

    def test_published_assets_are_never_completed_mutated_or_replaced(self):
        self.publish()
        self.github.releases[1]["assets"].pop(0)
        before = copy.deepcopy(self.github.writes)
        with self.assertRaisesRegex(ValueError, "published release is incomplete"):
            self.publish()
        self.assertEqual(self.github.writes, before)

    def test_newer_release_appearing_before_promotion_is_not_regressed(self):
        original = publish.latest_identity
        calls = 0
        def latest(github):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"version": "0.1.8", "sequence": 6}
            return original(github)
        with mock.patch.object(publish, "latest_identity", side_effect=latest):
            self.assertEqual(self.publish()["status"], "superseded-draft")
        self.assertTrue(self.github.releases[1]["draft"])
        self.assertIsNone(self.github.latest)


class WorkflowTests(unittest.TestCase):
    def test_release_uses_same_run_successful_matrix_artifacts(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/build.yml").read_text()
        job = text.split("  publish-game-update:\n", 1)[1]
        self.assertIn("needs: [build]", job)
        self.assertIn("github.event_name == 'push'", job)
        for branch in identity.RELEASE_BRANCHES:
            self.assertIn(f"refs/heads/{branch}", job)
        self.assertIn("RUST_DUTY_BUILD_RESULT: ${{ needs.build.result }}", job)
        self.assertIn("group: rust-duty-release-channel", job)
        self.assertIn("cancel-in-progress: false", job)
        self.assertNotIn("run-id:", job)
        self.assertNotIn("aella/release-channel", job)
        self.assertNotIn("aella/layered-locomotion-integration-r1", job)
        self.assertNotIn("rust-duty-launcher", job)
        self.assertEqual(text.count("RUST_DUTY_BUILD_VERSION: '0.1.5'"), 1)
        self.assertIn("tools/build_identity.py --root dist/game --platform windows", text)
        self.assertNotIn("tools/build_identity.py --root dist/game --platform linux", text)
        build = text.split("  build:\n", 1)[1].split("  publish-game-update:\n", 1)[0]
        self.assertNotIn("RUST_DUTY_BUILD_VERSION:", build)
        self.assertIn("run: python tools/ci_quality_checks.py", build)
        self.assertNotIn("continue-on-error:", build)
        self.assertLess(build.index("run: python tools/ci_quality_checks.py"),
                        build.index("name: Stage complete Windows game"))
        self.assertEqual(ci_quality_checks.pipelines()['updater'], [
            ['cargo', 'fmt', '--manifest-path', 'updater/Cargo.toml', '--all', '--', '--check'],
            ['cargo', 'clippy', '--manifest-path', 'updater/Cargo.toml', '--locked', '--all-targets', '--', '-D', 'warnings'],
            ['cargo', 'test', '--manifest-path', 'updater/Cargo.toml', '--locked'],
        ])


if __name__ == "__main__":
    unittest.main()
