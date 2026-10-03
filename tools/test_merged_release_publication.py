"""Offline regressions for ledger-bound merged-PR game publication.

No live credentials, releases, tags, or ledger writes are used by these tests.
The ledger interface is mocked so publisher authority remains independently
testable while allocation has its own dedicated test suite.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

import build_identity
import publish_game_build as publisher
import test_publish_game_build as fixtures


REPOSITORY = "RHS059/rust_duty"
WORKFLOW = ".github/workflows/merged-game-release.yml"
SOURCE = "a" * 40
CONTROL_SOURCE = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


def merged_environment():
    return {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_RUN_NUMBER": "17",
        "GITHUB_RUN_ID": "1007",
        "GITHUB_SHA": CONTROL_SOURCE,
        "GITHUB_REF_NAME": "main",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "pull_request_target",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW}@refs/heads/main",
        "RUST_DUTY_BUILD_VERSION": "0.1.6",
        "RUST_DUTY_RELEASE_SEQUENCE": "6",
        "RUST_DUTY_RELEASE_PR": "61",
        "RUST_DUTY_SOURCE_SHA": SOURCE,
        "RUST_DUTY_BUILD_RESULT": "success",
    }


class MergedContextTests(unittest.TestCase):
    def test_source_commit_is_allocation_not_later_workflow_head(self):
        actual = build_identity.context(merged_environment(), publication=True)
        self.assertEqual(actual["source"]["commit"], SOURCE)
        self.assertNotEqual(actual["source"]["commit"], CONTROL_SOURCE)
        self.assertEqual(actual["source"]["branch"], "main")
        self.assertEqual(actual["source"]["workflow"], WORKFLOW)
        self.assertEqual(actual["source"]["run_id"], 1007)
        self.assertEqual(actual["merge"], {"pull_request": 61, "base": "main"})
        self.assertEqual((actual["version"], actual["sequence"]), ("0.1.6", 6))

    def test_same_allocation_keeps_version_across_run_attempts_and_numbers(self):
        first = build_identity.context(merged_environment())
        for number, attempt in [("18", "2"), ("9000", "999")]:
            env = {**merged_environment(), "GITHUB_RUN_NUMBER": number,
                   "GITHUB_RUN_ATTEMPT": attempt}
            actual = build_identity.context(env)
            self.assertEqual(actual["version"], first["version"])
            self.assertEqual(actual["sequence"], first["sequence"])
            self.assertEqual(actual["source"]["run_id"], first["source"]["run_id"])

    def test_only_trusted_main_merge_recovery_and_schedule_contexts_are_valid(self):
        for event in ("pull_request_target", "workflow_dispatch", "schedule"):
            env = {**merged_environment(), "GITHUB_EVENT_NAME": event}
            with self.subTest(event=event):
                self.assertEqual(build_identity.context(env, publication=True)["version"], "0.1.6")

    def test_untrusted_context_and_invalid_patch_allocations_fail_closed(self):
        cases = [
            ("GITHUB_REPOSITORY", "someone/fork"),
            ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_EVENT_NAME", "repository_dispatch"),
            ("GITHUB_REF", "refs/heads/aella/example"),
            ("GITHUB_REF", "refs/pull/61/merge"),
            ("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/{WORKFLOW}@refs/heads/feature"),
            ("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/.github/workflows/build.yml@refs/heads/main"),
            ("GITHUB_WORKFLOW_REF", ""),
            ("RUST_DUTY_SOURCE_SHA", "main"),
            ("RUST_DUTY_SOURCE_SHA", "A" * 40),
            ("RUST_DUTY_RELEASE_PR", "0"),
            ("RUST_DUTY_RELEASE_PR", "061"),
            ("RUST_DUTY_RELEASE_PR", "61\n"),
            ("RUST_DUTY_RELEASE_SEQUENCE", "5"),
            ("RUST_DUTY_RELEASE_SEQUENCE", "06"),
            ("RUST_DUTY_RELEASE_SEQUENCE", str(2**64)),
            ("RUST_DUTY_BUILD_VERSION", "0.1.5"),
            ("RUST_DUTY_BUILD_VERSION", "0.1.7"),
            ("RUST_DUTY_BUILD_VERSION", "0.2.6"),
            ("RUST_DUTY_BUILD_VERSION", "0.1.6-preview"),
        ]
        for key, value in cases:
            env = {**merged_environment(), key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                build_identity.context(env, publication=True)

    def test_failed_skipped_cancelled_or_unproven_matrix_never_authorizes_publication(self):
        for result in ("failure", "cancelled", "skipped", "", None):
            env = {**merged_environment(), "RUST_DUTY_BUILD_RESULT": result}
            with self.subTest(result=result), self.assertRaises(ValueError):
                build_identity.context(env, publication=True)

    def test_draft_validation_has_no_merged_allocation_and_does_not_increment(self):
        env = fixtures.environment(number=700, run_id=8000)
        env["GITHUB_EVENT_NAME"] = "pull_request"
        env["GITHUB_REF"] = "refs/pull/61/merge"
        env["GITHUB_REF_NAME"] = "61/merge"
        actual = build_identity.context(env)
        self.assertEqual((actual["version"], actual["sequence"]), ("0.1.5", 5))
        self.assertNotIn("merge", actual)
        with self.assertRaises(ValueError):
            build_identity.context(env, publication=True)


class MergedAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.identity = build_identity.context(merged_environment(), publication=True)
        self.state = {"sentinel": "a ledger snapshot, validated by the mocked ledger"}
        self.ledger = types.ModuleType("merge_release_ledger")
        self.ledger.read_state = mock.Mock(return_value=("ledger-tip", self.state))
        self.ledger.validate_record = mock.Mock()
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(sys.modules, {"merge_release_ledger": self.ledger}).start()
        self.pr = {
            "number": 61, "merged": True, "state": "closed", "draft": False,
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            "merge_commit_sha": SOURCE,
        }
        self.relation = {"status": "ahead"}
        self.run = {
            "id": 1007, "repository": {"full_name": REPOSITORY},
            "path": WORKFLOW, "head_branch": "main", "event": "pull_request_target",
            "status": "in_progress", "conclusion": None,
        }
        self.jobs = [
            {"id": 10, "name": "build / ubuntu-latest", "run_id": 1007,
             "head_sha": CONTROL_SOURCE, "status": "completed", "conclusion": "success"},
            {"id": 11, "name": "build / windows-latest", "run_id": 1007,
             "head_sha": CONTROL_SOURCE, "status": "completed", "conclusion": "success"},
        ]
        self.github = mock.Mock()
        self.github.api.side_effect = self.api

    def api(self, endpoint, **kwargs):
        self.assertNotIn("payload", kwargs, "authority verification must be read-only")
        jobs = re.fullmatch(r"actions/runs/1007/jobs\?filter=all&per_page=100&page=([1-9][0-9]*)", endpoint)
        if jobs:
            start = (int(jobs.group(1)) - 1) * 100
            return {"jobs": copy.deepcopy(self.jobs[start:start + 100])}
        values = {
            "pulls/61": self.pr,
            f"compare/{SOURCE}...main?per_page=1": self.relation,
            "actions/runs/1007": self.run,
        }
        if endpoint not in values:
            self.fail(f"Unexpected authority request: {endpoint}")
        return copy.deepcopy(values[endpoint])

    def test_exact_durable_allocation_and_canonical_run_are_checked_before_trust(self):
        publisher.verify_merged_authority(self.github, self.identity)
        self.ledger.read_state.assert_called_once_with(self.github)
        self.ledger.validate_record.assert_called_once_with(
            self.state, 61, SOURCE, "0.1.6", 6, 1007)
        self.assertEqual(self.github.api.call_count, 4)

    def test_missing_or_conflicting_ledger_prevents_any_later_api_access(self):
        self.ledger.validate_record.side_effect = ValueError("canonical run conflicts")
        with self.assertRaisesRegex(ValueError, "canonical run conflicts"):
            publisher.verify_merged_authority(self.github, self.identity)
        self.github.api.assert_not_called()

    def test_unreadable_ledger_is_not_assumed_empty_or_safe(self):
        self.ledger.read_state.side_effect = RuntimeError("ledger unavailable")
        with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
            publisher.verify_merged_authority(self.github, self.identity)
        self.ledger.validate_record.assert_not_called()
        self.github.api.assert_not_called()

    def test_unmerged_draft_wrong_base_or_wrong_source_pr_is_rejected(self):
        cases = [
            {"number": 62}, {"merged": False}, {"merged": "true"},
            {"state": "open"}, {"draft": True}, {"draft": None},
            {"merge_commit_sha": CONTROL_SOURCE},
            {"base": {"ref": "development", "repo": {"full_name": REPOSITORY}}},
            {"base": {"ref": "main", "repo": {"full_name": "someone/fork"}}},
        ]
        original = copy.deepcopy(self.pr)
        for changes in cases:
            self.pr = {**copy.deepcopy(original), **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)

    def test_source_must_still_be_an_ancestor_of_main(self):
        for status in ("behind", "diverged", "", None):
            self.relation = {"status": status}
            with self.subTest(status=status), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)
        self.relation = {"status": "identical"}
        publisher.verify_merged_authority(self.github, self.identity)

    def test_wrong_canonical_run_repository_workflow_branch_or_event_is_rejected(self):
        cases = [
            {"id": 1008}, {"repository": {"full_name": "someone/fork"}},
            {"path": ".github/workflows/build.yml"}, {"head_branch": "feature"},
            {"event": "pull_request"}, {"event": "push"},
        ]
        original = copy.deepcopy(self.run)
        for changes in cases:
            self.run = {**copy.deepcopy(original), **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)

    def test_explicitly_failed_or_cancelled_canonical_run_is_not_trusted(self):
        for conclusion in ("failure", "cancelled", "timed_out", "skipped", "action_required"):
            self.run.update(status="completed", conclusion=conclusion)
            with self.subTest(conclusion=conclusion), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)

    def test_completed_successful_canonical_run_is_valid_for_idempotent_verification(self):
        self.run.update(status="completed", conclusion="success")
        publisher.verify_merged_authority(self.github, self.identity)

    def test_missing_failed_cancelled_or_in_progress_native_platform_is_rejected(self):
        original = copy.deepcopy(self.jobs)
        for platform in (0, 1):
            for status, conclusion in (("completed", "failure"), ("completed", "cancelled"),
                                       ("completed", "skipped"), ("in_progress", None)):
                self.jobs = copy.deepcopy(original)
                self.jobs[platform].update(status=status, conclusion=conclusion)
                with self.subTest(platform=platform, status=status, conclusion=conclusion), self.assertRaises(ValueError):
                    publisher.verify_merged_authority(self.github, self.identity)
            self.jobs = [copy.deepcopy(original[1 - platform])]
            with self.subTest(platform=platform, missing=True), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)

    def test_jobs_must_have_exact_names_and_canonical_run_ids(self):
        original = copy.deepcopy(self.jobs)
        for platform in (0, 1):
            for changes in ({"run_id": 1008}, {"name": "ubuntu-latest"},
                            {"name": original[platform]["name"] + " malicious suffix"}):
                self.jobs = copy.deepcopy(original)
                self.jobs[platform].update(changes)
                with self.subTest(platform=platform, changes=changes), self.assertRaises(ValueError):
                    publisher.verify_merged_authority(self.github, self.identity)

    def test_newest_failed_job_overrides_older_success_even_when_api_order_changes(self):
        original = copy.deepcopy(self.jobs)
        for reverse in (False, True):
            newer = {**original[0], "id": 999, "conclusion": "failure"}
            self.jobs = [newer, *copy.deepcopy(original)]
            if reverse:
                self.jobs.reverse()
            with self.subTest(reverse=reverse), self.assertRaises(ValueError):
                publisher.verify_merged_authority(self.github, self.identity)

    def test_newest_successful_retry_can_reuse_other_platform_original_success(self):
        older_failure = {**self.jobs[0], "id": 1, "conclusion": "failure"}
        self.jobs.append(older_failure)
        publisher.verify_merged_authority(self.github, self.identity)

    def test_native_jobs_beyond_first_page_are_checked(self):
        native = copy.deepcopy(self.jobs)
        self.jobs = [{"id": 100 + i, "name": f"unrelated job {i}", "run_id": 1007,
                      "status": "completed", "conclusion": "success"}
                     for i in range(100)] + native
        publisher.verify_merged_authority(self.github, self.identity)
        self.assertIn(mock.call("actions/runs/1007/jobs?filter=all&per_page=100&page=2"),
                      self.github.api.call_args_list)

    def test_failed_authority_prevents_preparation_and_publication(self):
        self.ledger.validate_record.side_effect = ValueError("allocation mismatch")
        with mock.patch.object(publisher, "GitHub", return_value=self.github), \
                mock.patch.object(publisher.build_identity, "context", return_value=self.identity), \
                mock.patch.object(publisher, "prepare") as prepare, \
                mock.patch.object(publisher, "publish") as publish, \
                mock.patch.object(sys, "argv", ["publish_game_build.py", "--tested", "tested", "--output", "out"]):
            with self.assertRaisesRegex(ValueError, "allocation mismatch"):
                publisher.main()
        prepare.assert_not_called()
        publish.assert_not_called()


class MergedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.tested = self.root / "tested"
        self.output = self.root / "release"
        self.identity = build_identity.context(merged_environment(), publication=True)
        self.github = fixtures.FakeGitHub()
        for platform, (_, executable, _, magic) in build_identity.TARGETS.items():
            root = self.tested / platform
            root.mkdir(parents=True)
            (root / executable).write_bytes(magic + b"merged-source fixture")
            with mock.patch.object(build_identity.subprocess, "check_output", return_value="0.1.6\n"):
                build_identity.stamp(root, platform, merged_environment())
        with mock.patch.object(publisher.package_game, "stage", side_effect=fixtures.PublicationTests.fixture_stage):
            publisher.prepare(self.tested, self.output, self.identity)

    def add_baseline(self, version="0.1.5", sequence=5):
        return fixtures.PublicationTests.add_baseline(self, version, sequence)

    def publish(self):
        return publisher.publish(self.github, self.output, self.identity)

    def test_complete_newer_merge_becomes_latest_with_exact_source_and_all_assets(self):
        self.add_baseline()
        self.assertEqual(self.publish()["status"], "published")
        release = self.github.releases[self.github.latest]
        self.assertEqual(release["tag_name"], "v0.1.6")
        self.assertEqual(release["target_commitish"], SOURCE)
        self.assertEqual(len(release["assets"]), 9)
        self.assertIn("merged PR #61", release["body"])
        self.assertEqual(publisher.latest_identity(self.github), {"version": "0.1.6", "sequence": 6})

    def test_older_complete_merge_is_public_without_regressing_latest(self):
        baseline = self.add_baseline("0.1.7", 7)
        self.assertEqual(self.publish()["status"], "published")
        self.assertEqual(self.github.latest, baseline["id"])
        older = next(item for item in self.github.releases.values() if item["tag_name"] == "v0.1.6")
        self.assertIs(older["draft"], False)
        self.assertEqual(len(older["assets"]), 9)
        self.assertEqual(older["make_latest"], "false")
        self.assertEqual(publisher.latest_identity(self.github), {"version": "0.1.7", "sequence": 7})
        self.assertFalse(any(payload.get("make_latest") == "true" for _, payload in self.github.writes))

    def test_exact_retry_of_older_public_release_performs_no_writes(self):
        self.add_baseline("0.1.7", 7)
        self.publish()
        before = (copy.deepcopy(self.github.writes), list(self.github.uploads), self.github.latest)
        self.assertEqual(self.publish()["status"], "already-published")
        self.assertEqual((self.github.writes, self.github.uploads, self.github.latest), before)

    def test_interrupted_older_release_remains_draft_and_resumes_only_missing_assets(self):
        baseline = self.add_baseline("0.1.7", 7)
        self.github.interrupt_after = 3
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.publish()
        self.assertEqual(self.github.latest, baseline["id"])
        self.assertTrue(self.github.releases[2]["draft"])
        self.github.interrupt_after = None
        self.publish()
        self.assertFalse(self.github.releases[2]["draft"])
        self.assertEqual(len(self.github.uploads), 9)
        self.assertEqual(len(set(self.github.uploads)), 9)
        self.assertEqual(self.github.latest, baseline["id"])

    def test_newer_release_arriving_during_upload_keeps_latest(self):
        self.add_baseline()
        real_latest = publisher.latest_identity
        calls = 0

        def changing_latest(github):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.add_baseline("0.1.7", 7)
            return real_latest(github)

        with mock.patch.object(publisher, "latest_identity", side_effect=changing_latest):
            self.publish()
        self.assertEqual(real_latest(self.github), {"version": "0.1.7", "sequence": 7})
        older = next(item for item in self.github.releases.values() if item["tag_name"] == "v0.1.6")
        self.assertIs(older["draft"], False)
        self.assertEqual(older["make_latest"], "false")

    def test_different_run_cannot_replace_canonical_draft_bytes_or_provenance(self):
        self.github.interrupt_after = 1
        with self.assertRaises(RuntimeError):
            self.publish()
        self.github.interrupt_after = None
        different = copy.deepcopy(self.identity)
        different["source"]["run_id"] += 1
        different["source"]["run_url"] = f"https://github.com/{REPOSITORY}/actions/runs/1008"
        before = (copy.deepcopy(self.github.writes), list(self.github.uploads))
        with self.assertRaisesRegex(ValueError, "identity differs"):
            publisher.publish(self.github, self.output, different)
        self.assertEqual((self.github.writes, self.github.uploads), before)

    def test_only_exact_source_version_and_canonical_run_artifacts_are_accepted(self):
        for platform in build_identity.TARGETS:
            path = self.tested / platform / build_identity.IDENTITY_FILE
            original = path.read_text()
            for field, value in (("commit", CONTROL_SOURCE), ("run_id", 1008)):
                data = json.loads(original)
                data["source"][field] = value
                path.write_text(json.dumps(data))
                with self.subTest(platform=platform, field=field), self.assertRaises(ValueError):
                    publisher.prepare(self.tested, self.root / f"bad-{platform}-{field}", self.identity)
            path.write_text(original)
        self.assertFalse(self.github.writes)

    def test_missing_platform_and_incomplete_output_cannot_become_public(self):
        (self.tested / "windows" / build_identity.IDENTITY_FILE).unlink()
        with self.assertRaisesRegex(ValueError, "missing or unsafe"):
            publisher.prepare(self.tested, self.root / "missing-platform", self.identity)
        (self.output / publisher.PROVENANCE).unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.publish()
        self.assertFalse(self.github.writes)
        self.assertFalse(self.github.uploads)


class MergedWorkflowContractTests(unittest.TestCase):
    def test_trusted_closed_event_and_recovery_are_available(self):
        text = (ROOT / WORKFLOW).read_text()
        self.assertRegex(text, r"pull_request_target:\s+types: \[closed\]\s+branches: \[main\]")
        self.assertIn("github.event.pull_request.merged == true", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("schedule:", text)
        self.assertIn("queue: max", text)
        self.assertNotIn("cancel-in-progress: true", text)

    def test_writes_are_job_scoped_and_no_persistent_or_extra_credentials_are_used(self):
        text = (ROOT / WORKFLOW).read_text()
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read\njobs:")
        self.assertEqual(len(re.findall(r"(?m)^      contents: write$", text)), 2)
        self.assertNotRegex(text, r"(?m)^\s+(?:actions|id-token|pull-requests): write$")
        self.assertNotRegex(text, r"secrets\.|write-all|persist-credentials: true|secrets: inherit")
        self.assertEqual(text.count("GH_TOKEN: ${{ github.token }}"), 2)
        for filename in ("build.yml", "blender-assets.yml", "walk-assets.yml", "ads-assets.yml", "directional-assets.yml"):
            source = (ROOT / ".github/workflows" / filename).read_text()
            with self.subTest(workflow=filename):
                self.assertNotRegex(source, r"(?m)^\s+\S+: write$")
                self.assertNotIn("GH_TOKEN:", source)
                self.assertNotIn("secrets: inherit", source)

    def test_publisher_requires_success_and_consumes_both_same_run_artifacts(self):
        text = (ROOT / WORKFLOW).read_text()
        section = text.split("\n  publish:\n", 1)[1]
        self.assertIn("needs: [allocate, build]", section)
        self.assertIn("needs.build.result == 'success'", section)
        self.assertIn("ref: ${{ needs.allocate.outputs.commit_sha }}", section)
        self.assertIn("name: vector-range-windows-x64", section)
        self.assertIn("name: vector-range-linux-x64", section)
        self.assertNotIn("run-id:", section)
        self.assertNotIn("head.sha", section)
        self.assertIn("persist-credentials: false", section)

    def test_publisher_has_read_permission_for_independent_run_and_pr_checks(self):
        text = (ROOT / WORKFLOW).read_text()
        section = text.split("\n  publish:\n", 1)[1]
        permissions = section.split("    permissions:\n", 1)[1].split("    concurrency:\n", 1)[0]
        self.assertIn("      actions: read\n", permissions)
        self.assertIn("      pull-requests: read\n", permissions)

    def test_all_asset_and_binary_checkouts_use_allocated_source(self):
        for filename in ("build.yml", "blender-assets.yml", "walk-assets.yml", "ads-assets.yml", "directional-assets.yml"):
            text = (ROOT / ".github/workflows" / filename).read_text()
            with self.subTest(workflow=filename):
                self.assertIn("source-ref:", text)
                self.assertIn("ref: ${{ inputs.source-ref || github.sha }}", text)
                self.assertIn("persist-credentials: false", text)


if __name__ == "__main__":
    unittest.main()
