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
from urllib.parse import parse_qs, urlsplit

import build_identity as identity
import publish_game_build as publish


def environment(number=10, run_id=1000):
    return {"GITHUB_REPOSITORY": "RHS059/rust_duty", "GITHUB_RUN_NUMBER": str(number),
            "GITHUB_RUN_ID": str(run_id), "GITHUB_SHA": "a" * 40,
            "GITHUB_REF_NAME": "aella/automatic-game-updates-r1",
            "GITHUB_REF": "refs/heads/aella/automatic-game-updates-r1",
            "GITHUB_EVENT_NAME": "push", "RUST_DUTY_BUILD_VERSION": "0.1.5",
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
                release["upload_url"] = f'https://uploads.github.com/repos/RHS059/rust_duty/releases/{release["id"]}/assets{{?name,label}}'
                self.releases[release["id"]] = release
            else:
                release = self.releases[int(endpoint.split("/")[-1])]
                release.update(payload)
                if payload.get("draft") is False:
                    self.tags[release["tag_name"]] = release["target_commitish"]
                    if payload.get("make_latest") == "true":
                        self.latest = release["id"]
            return copy.deepcopy(release)
        if endpoint.startswith("releases?per_page="):
            query = parse_qs(urlsplit(endpoint).query)
            page, per_page = int(query["page"][0]), int(query["per_page"][0])
            values = list(self.releases.values())
            return copy.deepcopy(values[(page - 1) * per_page:page * per_page])
        if endpoint == "releases/latest":
            value = self.releases.get(self.latest)
        elif endpoint.startswith("releases/tags/"):
            value = next((r for r in self.releases.values() if r["tag_name"] == endpoint[14:] and not r["draft"]), None)
        elif endpoint.startswith("git/ref/tags/"):
            sha = self.tags.get(endpoint[13:])
            value = None if sha is None else {"object": {"type": "commit", "sha": sha}}
        else:
            value = self.releases.get(int(endpoint.split("/")[-1]))
        if value is None and not missing_ok:
            raise RuntimeError("HTTP 404")
        return copy.deepcopy(value)

    def upload(self, known_release, path):
        if self.interrupt_after is not None and len(self.uploads) >= self.interrupt_after:
            raise RuntimeError("simulated interrupted upload")
        release = self.releases[known_release["id"]]
        publish.upload_url(known_release, path.name)
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
    def test_one_time_version_and_sequence_do_not_increment_for_draft_pushes(self):
        item = identity.context(environment(), publication=True)
        self.assertEqual(item["version"], "0.1.5")
        self.assertEqual(item["sequence"], 5)
        self.assertEqual(item["source"]["commit"], "a" * 40)
        self.assertEqual(identity.context(environment(11, 1002))["version"], "0.1.5")

    def test_fail_closed_event_repository_branch_version_and_matrix_result(self):
        for key, value in [("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_EVENT_NAME", "workflow_dispatch"),
                           ("GITHUB_REPOSITORY", "someone/fork"), ("GITHUB_REF_NAME", "main"),
                           ("GITHUB_REF", "refs/pull/1/merge"), ("RUST_DUTY_BUILD_RESULT", "failure"),
                           ("RUST_DUTY_BUILD_RESULT", "cancelled"), ("RUST_DUTY_BUILD_RESULT", "skipped"),
                           ("RUST_DUTY_BUILD_VERSION", "0.1.4"), ("GITHUB_SHA", "main"),
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
                with mock.patch.object(identity.subprocess, "check_output", return_value="0.1.5\n") as run:
                    identity.stamp(root, platform, environment())
                self.assertEqual(run.call_args.args[0], [str(binary.resolve()), "--build-version"])
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


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tested = self.root / "tested"
        self.output = self.root / "release"
        self.identity = identity.context(environment(), publication=True)
        self.github = FakeGitHub()
        for platform, (_, executable, _, magic) in identity.TARGETS.items():
            source = self.tested / platform
            source.mkdir(parents=True)
            (source / executable).write_bytes(magic + b"native fixture")
            with mock.patch.object(identity.subprocess, "check_output", return_value="0.1.5\n"):
                identity.stamp(source, platform, environment())
        with mock.patch.object(publish.package_game, "stage", side_effect=self.fixture_stage) as stage:
            self.provenance = publish.prepare(self.tested, self.output, self.identity)
        self.assertEqual(stage.call_count, 4)
        self.assertTrue(all(call.kwargs["require_generated"] for call in stage.call_args_list))
        self.assertEqual(sum(call.kwargs.get("update", False) for call in stage.call_args_list), 2)

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
        for target, executable, _, _ in identity.TARGETS.values():
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
        self.assertEqual(len(list(self.output.iterdir())), 9)
        self.assertEqual(self.provenance["source"], self.identity["source"])
        for platform, (target, executable, label, _) in identity.TARGETS.items():
            manifest = json.loads((self.output / f"update-{target}.json").read_text())
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(manifest["version"], "0.1.5")
            self.assertEqual(manifest["sequence"], 5)
            self.assertEqual(manifest["deltas"], [])
            bundle = (self.output / manifest["bundle"]["name"]).read_bytes()
            self.assertIn(b"assets/reload/asset.vra", bundle)
            self.assertNotIn(b"settings.cfg", bundle)
            with zipfile.ZipFile(self.output / f"Rust-Duty-0.1.5-{label}-x64.zip") as archive:
                self.assertIn("settings.cfg", archive.namelist())
                self.assertEqual(archive.getinfo(executable).external_attr >> 16, 0o100755)
        again = self.root / "again"
        with mock.patch.object(publish.package_game, "stage", side_effect=self.fixture_stage):
            publish.prepare(self.tested, again, self.identity)
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (again / path.name).read_bytes(), path.name)

    def test_wrong_source_artifact_and_missing_generated_assets_fail_closed(self):
        (self.tested / "linux/vector-range").write_bytes(b"\x7fELFwrong run")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            publish.prepare(self.tested, self.root / "bad", self.identity)
        self.assertFalse((self.root / "bad").exists())
        with self.assertRaises(ValueError):
            publish.package_game.stage(self.tested / "windows", "vector-range.exe",
                                       self.root / "bad-payload", update=True, require_generated=True)

    def test_artifact_identity_cannot_be_reused_from_a_different_source_run(self):
        path = self.tested / "linux" / identity.IDENTITY_FILE
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
        self.assertEqual(len(self.github.uploads), 9)
        self.assertEqual(publish.latest_identity(self.github), {"version": "0.1.5", "sequence": 5})
        self.assertTrue(all(r.get("draft") is False for r in self.github.releases.values()))
        before = copy.deepcopy(self.github.writes)
        self.assertEqual(self.publish()["status"], "already-published")
        self.assertEqual(self.github.writes, before)
        self.assertEqual(len(self.github.uploads), 9)

    def test_interrupted_draft_resumes_only_missing_assets(self):
        self.add_baseline()
        self.github.interrupt_after = 3
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.publish()
        self.assertEqual(self.github.releases[2]["draft"], True)
        self.assertEqual(publish.latest_identity(self.github)["version"], "0.1.3")
        self.github.interrupt_after = None
        self.assertEqual(self.publish()["status"], "published")
        self.assertEqual(len(self.github.uploads), 9)
        self.assertEqual(len(set(self.github.uploads)), 9)

    def test_out_of_order_older_run_cannot_regress_latest(self):
        self.add_baseline("0.1.6", 6)
        self.assertEqual(self.publish()["status"], "superseded")
        self.assertFalse(self.github.writes)
        self.assertFalse(self.github.uploads)

    def test_sequence_version_conflicts_fail_closed(self):
        for version, sequence in [("0.1.6", 4), ("0.1.4", 6), ("0.1.5", 4), ("0.1.4", 5)]:
            with self.subTest(version=version, sequence=sequence), self.assertRaises(ValueError):
                publish.publication_order(self.identity, {"version": version, "sequence": sequence})

    def test_mismatched_latest_platforms_and_missing_bundles_fail_closed(self):
        baseline = self.add_baseline()
        manifest = next(a for a in baseline["assets"] if a["name"].startswith("update-"))
        blob = json.loads(self.github.contents[manifest["id"]])
        blob["sequence"] = 999
        self.github.contents[manifest["id"]] = json.dumps(blob).encode()
        with self.assertRaisesRegex(ValueError, "identities disagree"):
            self.publish()
        self.assertFalse(self.github.writes)
        baseline["assets"] = [a for a in baseline["assets"] if not a["name"].endswith(".rdb")]
        with self.assertRaisesRegex(ValueError, "lacks complete update bundle"):
            self.publish()

    def test_existing_tag_on_other_commit_is_never_repointed(self):
        self.github.tags["v0.1.5"] = "b" * 40
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
                return {"version": "0.1.6", "sequence": 6}
            return original(github)
        with mock.patch.object(publish, "latest_identity", side_effect=latest):
            self.assertEqual(self.publish()["status"], "superseded-draft")
        self.assertTrue(self.github.releases[1]["draft"])
        self.assertIsNone(self.github.latest)

    def seed_interrupted_recovery_draft(self):
        self.github.interrupt_after = 7
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.publish()
        self.github.interrupt_after = None
        self.assertEqual(set(path.name for path in self.output.iterdir()) -
                         set(publish.release_assets(self.github.releases[1])),
                         {"vector-range.exe", "vector-range-linux-x64"})

    def test_recovery_draft_by_tag_404_resumes_same_id_and_only_two_missing_files(self):
        self.seed_interrupted_recovery_draft()
        self.assertIsNone(self.github.api("releases/tags/v0.1.5", missing_ok=True))
        before = len(self.github.writes)
        result = publish.publish(self.github, self.output, self.identity, recovery_release_id=1)
        self.assertEqual(result["status"], "published")
        self.assertEqual(len(self.github.releases), 1)
        self.assertEqual(self.github.uploads[7:], ["vector-range-linux-x64", "vector-range.exe"])
        self.assertEqual([call[0] for call in self.github.writes[before:]], ["releases/1"])
        self.assertEqual(self.github.writes[-1][1], {"draft": False, "make_latest": "true"})

    def test_recovery_missing_or_wrong_draft_id_never_creates_or_uploads(self):
        with self.assertRaisesRegex(ValueError, "creation is forbidden"):
            publish.publish(self.github, self.output, self.identity, recovery_release_id=1)
        self.assertFalse(self.github.writes)
        self.seed_interrupted_recovery_draft()
        before = copy.deepcopy(self.github.writes)
        with self.assertRaisesRegex(ValueError, "required recovery draft"):
            publish.publish(self.github, self.output, self.identity, recovery_release_id=2)
        self.assertEqual(self.github.writes, before)
        self.assertEqual(len(self.github.uploads), 7)

    def test_recovery_cannot_add_unexpected_missing_assets(self):
        self.seed_interrupted_recovery_draft()
        self.github.releases[1]["assets"].pop(0)
        with self.assertRaisesRegex(ValueError, "only add the two known missing"):
            publish.publish(self.github, self.output, self.identity, recovery_release_id=1)
        self.assertEqual(len(self.github.uploads), 7)

    def test_duplicate_drafts_block_every_write(self):
        self.seed_interrupted_recovery_draft()
        duplicate = copy.deepcopy(self.github.releases[1])
        duplicate["id"] = 2
        self.github.releases[2] = duplicate
        before = copy.deepcopy(self.github.writes)
        with self.assertRaisesRegex(ValueError, "duplicate releases"):
            publish.publish(self.github, self.output, self.identity, recovery_release_id=1)
        self.assertEqual(self.github.writes, before)
        self.assertEqual(len(self.github.uploads), 7)

    def test_recovery_reuses_original_successful_matrix_and_artifact_identity(self):
        self.seed_interrupted_recovery_draft()
        original_api = self.github.api
        run = {"id": 1000, "head_sha": "a" * 40, "head_branch": environment()["GITHUB_REF_NAME"],
               "event": "push", "path": identity.WORKFLOW, "status": "completed",
               "conclusion": "failure", "run_number": 10,
               "repository": {"full_name": identity.REPOSITORY}}
        jobs = [{"name": name, "run_id": 1000, "head_sha": "a" * 40,
                 "status": "completed", "conclusion": "success"}
                for name in ("ubuntu-latest", "windows-latest")]
        def api(endpoint, **kwargs):
            if endpoint == "actions/runs/1000":
                return copy.deepcopy(run)
            if endpoint.startswith("actions/runs/1000/jobs?"):
                return {"jobs": copy.deepcopy(jobs)}
            return original_api(endpoint, **kwargs)
        with mock.patch.multiple(publish, RECOVERY_RELEASE_ID=1, RECOVERY_RUN_ID=1000,
                                 RECOVERY_COMMIT="a" * 40), mock.patch.object(self.github, "api", side_effect=api):
            recovered = publish.recovery_identity(self.github, self.tested, 1, 1000, "a" * 40,
                                          {**environment(), "GITHUB_REF": "refs/heads/" + publish.RECOVERY_EXECUTION_BRANCH})
            self.assertEqual(recovered, self.identity)
            jobs[1]["conclusion"] = "failure"
            with self.assertRaisesRegex(ValueError, "matrix job did not succeed"):
                publish.recovery_identity(self.github, self.tested, 1, 1000, "a" * 40,
                                          {**environment(), "GITHUB_REF": "refs/heads/" + publish.RECOVERY_EXECUTION_BRANCH})
            jobs[1]["conclusion"] = "success"
            run["head_sha"] = "b" * 40
            with self.assertRaisesRegex(ValueError, "provenance"):
                publish.recovery_identity(self.github, self.tested, 1, 1000, "a" * 40,
                                          {**environment(), "GITHUB_REF": "refs/heads/" + publish.RECOVERY_EXECUTION_BRANCH})
        self.assertEqual(len(self.github.uploads), 7)

    def test_upload_uses_validated_release_id_endpoint_and_exact_binary_body(self):
        self.seed_interrupted_recovery_draft()
        release = self.github.releases[1]
        path = self.output / "vector-range.exe"
        record = {**publish.release_update.asset(path), "state": "uploaded",
                  "digest": "sha256:" + publish.release_update.sha(path)}
        response = mock.Mock(returncode=0, stdout=json.dumps(record), stderr="")
        with mock.patch.object(publish.subprocess, "run", return_value=response) as call:
            publish.GitHub().upload(release, path)
        args = call.call_args.args[0]
        self.assertEqual(args[:3], ["gh", "api", "https://uploads.github.com/repos/RHS059/rust_duty/releases/1/assets?name=vector-range.exe"])
        self.assertIn(f"Content-Length: {path.stat().st_size}", args)
        self.assertEqual(args[-2:], ["--input", str(path)])
        for wrong in ("https://uploads.github.com.evil.example/assets", "http://uploads.github.com/assets",
                      "https://uploads.github.com/repos/RHS059/rust_duty/releases/2/assets{?name,label}"):
            with self.subTest(url=wrong), self.assertRaisesRegex(ValueError, "upload URL"):
                publish.upload_url({**release, "upload_url": wrong}, path.name)

    def seed_known_empty_orphan(self):
        self.seed_interrupted_recovery_draft()
        orphan = copy.deepcopy(self.github.releases[1])
        orphan.update(id=2, assets=[], upload_url="https://uploads.github.com/repos/RHS059/rust_duty/releases/2/assets{?name,label}")
        self.github.releases[2] = orphan
        return orphan

    def fast_recover(self, destination="fast-recovery"):
        with mock.patch.multiple(publish, RECOVERY_RELEASE_ID=1, RECOVERY_EMPTY_ORPHAN_ID=2,
                                 RECOVERY_PROVENANCE_SHA256=publish.release_update.sha(self.output / publish.PROVENANCE)), \
                mock.patch.object(publish, "prepare", side_effect=AssertionError("repacking forbidden")):
            return publish.recover(self.github, self.tested, self.root / destination, self.identity, 1)

    def test_fast_recovery_preserves_known_empty_orphan_and_never_repacks(self):
        orphan = copy.deepcopy(self.seed_known_empty_orphan())
        before = len(self.github.writes)
        original = copy.deepcopy(self.github.releases[1]["assets"])
        self.assertEqual(self.fast_recover()["status"], "published")
        self.assertEqual(self.github.releases[2], orphan)
        self.assertEqual(self.github.releases[1]["assets"][:7], original)
        self.assertEqual(self.github.uploads[7:], ["vector-range-linux-x64", "vector-range.exe"])
        self.assertEqual([item[0] for item in self.github.writes[before:]], ["releases/1"])
        self.assertFalse(any(path.suffix in (".zip", ".rdb") for path in (self.root / "fast-recovery").iterdir()))
        before = copy.deepcopy(self.github.writes)
        self.assertEqual(self.fast_recover("retry")["status"], "already-published")
        self.assertEqual(self.github.writes, before)
        self.assertEqual(self.github.releases[2], orphan)

    def test_generic_publication_still_rejects_known_empty_orphan(self):
        self.seed_known_empty_orphan()
        with mock.patch.multiple(publish, RECOVERY_RELEASE_ID=1, RECOVERY_EMPTY_ORPHAN_ID=2):
            with self.assertRaisesRegex(ValueError, "duplicate releases"):
                self.publish()
        self.assertEqual(len(self.github.uploads), 7)

    def test_fast_recovery_rejects_changed_nonempty_public_or_unknown_orphan(self):
        self.seed_known_empty_orphan()
        original = copy.deepcopy(self.github.releases[2])
        for field, value in (("draft", False), ("target_commitish", "b" * 40), ("body", "different notes"),
                             ("assets", [{"id": 999, "name": "unapproved", "size": 1, "state": "uploaded"}])):
            self.github.releases[2] = {**copy.deepcopy(original), field: value}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unchanged empty draft"):
                self.fast_recover(field)
        self.github.releases[2] = original
        self.github.releases[3] = {**copy.deepcopy(original), "id": 3}
        with self.assertRaisesRegex(ValueError, "duplicate releases"):
            self.fast_recover("unknown")
        self.assertEqual(len(self.github.uploads), 7)

    def test_fast_recovery_pinned_provenance_and_existing_hashes_are_mandatory(self):
        self.seed_known_empty_orphan()
        before = copy.deepcopy(self.github.writes)
        record = next(asset for asset in self.github.releases[1]["assets"] if asset["name"] == publish.PROVENANCE)
        old = self.github.contents[record["id"]]
        self.github.contents[record["id"]] = old + b" "
        with self.assertRaisesRegex(ValueError, "pinned original SHA"):
            self.fast_recover("wrong-proof")
        self.github.contents[record["id"]] = old
        self.github.releases[1]["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest differs"):
            self.fast_recover("wrong-existing-asset")
        self.assertEqual(self.github.writes, before)
        self.assertEqual(len(self.github.uploads), 7)

    def test_fast_recovery_missing_archive_cannot_be_reuploaded(self):
        self.seed_known_empty_orphan()
        self.github.releases[1]["assets"].pop(0)
        with self.assertRaisesRegex(ValueError, "only add the two known missing"):
            self.fast_recover()
        self.assertEqual(len(self.github.uploads), 7)


class ReleaseDiscoveryTests(unittest.TestCase):
    def test_complete_bounded_pagination_finds_draft_after_page_one(self):
        github = mock.Mock()
        filler = [{"id": number + 10, "tag_name": f"v9.0.{number}"} for number in range(100)]
        draft = {"id": 7, "tag_name": "v0.1.5", "draft": True}
        github.api.side_effect = [filler, [draft], draft]
        self.assertEqual(publish.find_release(github, "v0.1.5", required_id=7), draft)
        self.assertEqual([call.args[0] for call in github.api.call_args_list],
                         ["releases?per_page=100&page=1", "releases?per_page=100&page=2", "releases/7"])

    def test_pagination_limit_and_cross_page_duplicates_fail_closed(self):
        github = mock.Mock()
        filler = [{"id": number + 10, "tag_name": f"v9.0.{number}"} for number in range(100)]
        github.api.return_value = filler
        with mock.patch.object(publish, "MAX_API_PAGES", 2), self.assertRaisesRegex(ValueError, "pagination limit"):
            publish.find_release(github, "v0.1.5")
        filler[0] = {"id": 1, "tag_name": "v0.1.5"}
        github.api.side_effect = [filler, [{"id": 2, "tag_name": "v0.1.5"}]]
        with self.assertRaisesRegex(ValueError, "duplicate releases"):
            publish.find_release(github, "v0.1.5")


class WorkflowTests(unittest.TestCase):
    def test_release_uses_same_run_successful_matrix_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / ".github/workflows/build.yml").read_text()
        release = (root / ".github/workflows/merged-game-release.yml").read_text()
        job = release.split("  publish:\n", 1)[1]
        self.assertIn("needs: [allocate, build]", job)
        self.assertIn("needs.build.result == 'success'", job)
        self.assertIn("RUST_DUTY_BUILD_RESULT: ${{ needs.build.result }}", job)
        self.assertIn("group: rust-duty-release-channel", job)
        self.assertIn("cancel-in-progress: false", job)
        self.assertIn("queue: max", job)
        self.assertNotIn("run-id:", job)
        self.assertNotIn("publish-game-update:", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("tools/build_identity.py --root dist/game --platform windows", text)
        self.assertIn("tools/build_identity.py --root dist/game --platform linux", text)
        self.assertIn("cargo fmt --manifest-path updater/Cargo.toml --all -- --check", text)
        self.assertIn("cargo clippy --manifest-path updater/Cargo.toml --locked --all-targets -- -D warnings", text)
        self.assertIn("cargo test --manifest-path updater/Cargo.toml --locked", text)
        self.assertEqual(text.count("source-ref: ${{ inputs.source-ref || github.sha }}"), 4)
        for name in ("blender", "walk", "ads", "directional"):
            child = (root / f".github/workflows/{name}-assets.yml").read_text()
            self.assertIn("ref: ${{ inputs.source-ref || github.sha }}", child)
            self.assertIn("persist-credentials: false", child)


if __name__ == "__main__":
    unittest.main()
