"""Pure in-memory GitHub tests; no credentials, network or remote writes."""
import base64
import copy
import hashlib
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import merge_release_ledger as ledger


def digest(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()


def pr(number, commit, *, merged=True, draft=False, base="main", repository=ledger.REPOSITORY):
    return {"number": number, "state": "closed" if merged else "open", "merged": merged,
            "merged_at": "2026-10-03T12:00:00Z" if merged else None, "draft": draft,
            "merge_commit_sha": commit,
            "base": {"ref": base, "repo": {"full_name": repository}}}


class FakeGitHub:
    def __init__(self):
        self.main = ledger.ANCHOR_SHA
        self.ledger = None
        self.commits = {self.main: {"sha": self.main, "parents": [], "tree": {"sha": "0" * 40}}}
        self.trees, self.blobs, self.prs, self.associated = {}, {}, {}, {}
        self.writes, self.reads = [], []
        self.before_ref = None
        self.lose_reply = None
        self.after_discover = None

    def append(self, number=None, **kwargs):
        value = digest([self.main, number, len(self.commits)])
        self.commits[value] = {"sha": value, "parents": [{"sha": self.main}], "tree": {"sha": "0" * 40}}
        self.main = value
        if number is not None:
            self.prs[number] = pr(number, value, **kwargs)
            self.associated[value] = [number]
        return value

    def overwrite_state(self, state):
        previous = ledger.read_state(self)[1]
        # Deliberately bypass transition validation for corruption tests.
        content = json.dumps(state)
        tree = self.api("git/trees", payload={"tree": [{"path": ledger.STATE_FILE,
            "type": "blob", "mode": "100644", "content": content}]})
        commit = self.api("git/commits", payload={"message": "tamper", "tree": tree["sha"],
            "parents": [self.ledger] if self.ledger else []})
        self.ledger = commit["sha"]
        return previous

    def ref(self, name, commit):
        return {"ref": f"refs/heads/{name}", "object": {"type": "commit", "sha": commit}}

    def api(self, endpoint, *, payload=None, method=None, missing_ok=False):
        if payload is not None:
            self.writes.append((endpoint, copy.deepcopy(payload), method))
            if endpoint == "git/trees":
                items = []
                for node in payload["tree"]:
                    data = node["content"].encode()
                    blob_sha = digest(["blob", node["content"]])
                    self.blobs[blob_sha] = {"sha": blob_sha, "encoding": "base64", "size": len(data),
                                           "content": base64.b64encode(data).decode()}
                    items.append({key: node[key] for key in ("path", "mode", "type")} | {"sha": blob_sha})
                tree_sha = digest(["tree", items])
                value = {"sha": tree_sha, "truncated": False, "tree": items}
                self.trees[tree_sha] = value
            elif endpoint == "git/commits":
                commit_sha = digest(["commit", payload])
                value = {"sha": commit_sha, "parents": [{"sha": p} for p in payload["parents"]],
                         "tree": {"sha": payload["tree"]}}
                self.commits[commit_sha] = value
            elif endpoint in ("git/refs", f"git/refs/heads/{ledger.LEDGER_BRANCH}"):
                if self.before_ref:
                    callback, self.before_ref = self.before_ref, None
                    callback()
                if endpoint == "git/refs":
                    if payload["ref"] != f"refs/heads/{ledger.LEDGER_BRANCH}":
                        raise AssertionError("writes outside dedicated ledger branch")
                    if self.ledger is not None:
                        raise ledger.APIError("already exists", 422)
                    if self.commits[payload["sha"]]["parents"]:
                        raise AssertionError("initialization was not orphaned")
                else:
                    if method != "PATCH" or payload["force"] is not False:
                        raise AssertionError("missing nonforce PATCH")
                    if self.commits[payload["sha"]]["parents"] != [{"sha": self.ledger}]:
                        raise ledger.APIError("non-fast-forward", 422)
                self.ledger = payload["sha"]
                value = self.ref(ledger.LEDGER_BRANCH, self.ledger)
            else:
                raise AssertionError(f"unexpected write: {endpoint}")
            if self.lose_reply == endpoint:
                self.lose_reply = None
                raise ledger.APIError("lost reply")
            return copy.deepcopy(value)
        self.reads.append(endpoint)
        if endpoint == "git/ref/heads/main":
            if self.after_discover:
                callback, self.after_discover = self.after_discover, None
                callback()
            value = self.ref("main", self.main)
        elif endpoint == f"git/ref/heads/{ledger.LEDGER_BRANCH}":
            value = self.ref(ledger.LEDGER_BRANCH, self.ledger) if self.ledger else None
        elif endpoint.startswith("git/commits/"):
            value = self.commits[endpoint.rsplit("/", 1)[1]]
        elif endpoint.startswith("git/trees/"):
            value = self.trees[endpoint.rsplit("/", 1)[1]]
        elif endpoint.startswith("git/blobs/"):
            value = self.blobs[endpoint.rsplit("/", 1)[1]]
        elif endpoint.startswith("pulls?"):
            query = parse_qs(urlsplit(endpoint).query)
            page = int(query["page"][0])
            values = [p for p in self.prs.values() if p["state"] == "closed" and p["base"]["ref"] == "main"]
            value = values[(page - 1) * 100:page * 100]
        elif endpoint.startswith("pulls/"):
            value = self.prs[int(endpoint.split("/")[1])]
        elif endpoint.startswith("commits/"):
            query = parse_qs(urlsplit(endpoint).query)
            page = int(query["page"][0])
            numbers = self.associated.get(endpoint.split("/")[1], [])
            value = [{"number": n} for n in numbers[(page - 1) * 100:page * 100]]
        else:
            raise AssertionError(f"unexpected read: {endpoint}")
        if value is None and not missing_ok:
            raise ledger.APIError("not found", 404)
        return copy.deepcopy(value)


def request(number=None, run=100, *, event="workflow_dispatch", merge=None):
    return ledger.Request(event, run, ledger.ANCHOR_SHA, number, merge)


def env(name="workflow_dispatch", run=100):
    return {"GITHUB_REPOSITORY": ledger.REPOSITORY, "GITHUB_REF": ledger.BASE_REF,
            "GITHUB_WORKFLOW_REF": f"{ledger.REPOSITORY}/{ledger.WORKFLOW}@{ledger.BASE_REF}",
            "GITHUB_EVENT_NAME": name, "GITHUB_RUN_ID": str(run), "GITHUB_SHA": ledger.ANCHOR_SHA}


def event(value=None):
    result = {"repository": {"full_name": ledger.REPOSITORY}}
    if value is not None:
        result.update(action="closed", number=value["number"], pull_request=value)
    return result


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()

    def test_first_merge_starts_six_and_state_is_orphan_ledger_only(self):
        commit = self.github.append(20)
        result = ledger.allocate_release(self.github, request(20))
        self.assertEqual(result, {"version": "0.1.6", "release_sequence": "6", "commit_sha": commit,
            "pull_request": "20", "should_build": "true", "canonical_run_id": "100"})
        head, state = ledger.read_state(self.github)
        self.assertEqual(self.github.commits[head]["parents"], [])
        self.assertEqual(state["consumed"], {"version": "0.1.5", "sequence": 5})
        ledger.validate_record(state, 20, commit, "0.1.6", 6, 100)

    def test_reverse_arrival_allocates_in_first_parent_order(self):
        first = self.github.append(101)
        self.github.append()  # Direct pushes do not consume a version.
        last = self.github.append(9)  # PR numbers and timestamps do not define order.
        newer = ledger.allocate_release(self.github, request(9, 200))
        state = ledger.read_state(self.github)[1]
        self.assertEqual([(e["pr_number"], e["build_run_id"]) for e in state["entries"]], [(101, None), (9, 200)])
        self.assertEqual((newer["version"], newer["commit_sha"]), ("0.1.7", last))
        older = ledger.allocate_release(self.github, request(101, 201))
        self.assertEqual((older["version"], older["commit_sha"]), ("0.1.6", first))

    def test_retry_same_run_and_independent_duplicate_make_no_writes(self):
        self.github.append(1)
        original = ledger.allocate_release(self.github, request(1, 100))
        count = len(self.github.writes)
        self.assertEqual(ledger.allocate_release(self.github, request(1, 100)), original)
        result = ledger.allocate_release(self.github, request(1, 200))
        self.assertEqual(result["should_build"], "false")
        self.assertEqual(result["canonical_run_id"], "100")
        self.assertEqual(len(self.github.writes), count)

    def test_duplicate_does_not_mutate_even_if_new_merges_are_waiting(self):
        self.github.append(1)
        ledger.allocate_release(self.github, request(1, 100))
        self.github.append(2)
        count = len(self.github.writes)
        self.assertEqual(ledger.allocate_release(self.github, request(1, 200))["should_build"], "false")
        self.assertEqual(len(self.github.writes), count)

    def test_schedule_fills_oldest_unclaimed_and_retry_preserves_selection(self):
        self.github.append(1)
        self.github.append(2)
        ledger.allocate_release(self.github, request(2, 200))
        older = ledger.allocate_release(self.github, request(run=300, event="schedule"))
        self.assertEqual((older["pull_request"], older["version"]), ("1", "0.1.6"))
        self.github.append(3)
        count = len(self.github.writes)
        self.assertEqual(ledger.allocate_release(self.github, request(run=300, event="schedule")), older)
        self.assertEqual(len(self.github.writes), count)
        self.assertEqual(ledger.allocate_release(self.github, request(run=400, event="schedule"))["version"], "0.1.8")

    def test_no_pending_work_does_not_initialize_or_update_branch(self):
        self.github.append()
        self.assertEqual(ledger.allocate_release(self.github, request())["should_build"], "false")
        self.assertEqual(self.github.writes, [])
        self.github.append(1)
        ledger.allocate_release(self.github, request(1))
        count = len(self.github.writes)
        self.assertEqual(ledger.allocate_release(self.github, request(run=200))["canonical_run_id"], "")
        self.assertEqual(len(self.github.writes), count)

    def test_merge_squash_and_final_rebase_sha_each_get_one_increment(self):
        merge = self.github.append(1)
        self.github.commits[merge]["parents"].append({"sha": "e" * 40})
        self.github.append(2)  # Squash has one parent.
        middle = self.github.append()  # First replayed commit of a multi-commit rebase.
        final = self.github.append(3)
        self.github.associated[middle] = [3]
        result = ledger.allocate_release(self.github, request(3))
        self.assertEqual((result["version"], result["commit_sha"]), ("0.1.8", final))
        self.assertEqual(len(ledger.read_state(self.github)[1]["entries"]), 3)

    def test_open_draft_unmerged_and_other_bases_are_ignored(self):
        self.github.append(1, merged=False)
        self.github.append(2, draft=True)
        self.github.append(3, base="develop")
        self.github.append(4, repository="someone/else")
        self.github.append(5)
        result = ledger.allocate_release(self.github, request(5))
        self.assertEqual(result["version"], "0.1.6")
        self.assertEqual(len(ledger.read_state(self.github)[1]["entries"]), 1)

    def test_race_initialization_claim_cannot_be_overwritten(self):
        self.github.append(1)
        self.github.before_ref = lambda: ledger.allocate_release(self.github, request(1, 200))
        result = ledger.allocate_release(self.github, request(1, 100))
        self.assertEqual((result["should_build"], result["canonical_run_id"]), ("false", "200"))
        self.assertEqual(ledger.read_state(self.github)[1]["entries"][0]["build_run_id"], 200)

    def test_cas_race_on_existing_branch_preserves_both_claims(self):
        self.github.append(1)
        self.github.append(2)
        self.github.append(3)
        ledger.allocate_release(self.github, request(1, 100))
        self.github.before_ref = lambda: ledger.allocate_release(self.github, request(2, 200))
        result = ledger.allocate_release(self.github, request(3, 300))
        self.assertEqual(result["version"], "0.1.8")
        self.assertEqual([e["build_run_id"] for e in ledger.read_state(self.github)[1]["entries"]], [100, 200, 300])

    def test_lost_reply_initialization_reconciles_without_second_ref_write(self):
        self.github.append(1)
        self.github.lose_reply = "git/refs"
        self.assertEqual(ledger.allocate_release(self.github, request(1))["version"], "0.1.6")
        self.assertEqual(sum(e[0] == "git/refs" for e in self.github.writes), 1)

    def test_lost_reply_existing_branch_reconciles_without_second_ref_write(self):
        self.github.append(1)
        self.github.append(2)
        ledger.allocate_release(self.github, request(1))
        endpoint = f"git/refs/heads/{ledger.LEDGER_BRANCH}"
        self.github.lose_reply = endpoint
        self.assertEqual(ledger.allocate_release(self.github, request(2, 200))["version"], "0.1.7")
        self.assertEqual(sum(e[0] == endpoint for e in self.github.writes), 1)

    def test_lost_object_reply_is_safe_to_retry_before_ref_creation(self):
        for endpoint in ("git/trees", "git/commits"):
            with self.subTest(endpoint=endpoint):
                github = FakeGitHub()
                github.append(1)
                github.lose_reply = endpoint
                self.assertEqual(ledger.allocate_release(github, request(1))["version"], "0.1.6")
                self.assertEqual(sum(e[0] == "git/refs" for e in github.writes), 1)

    def test_rewritten_main_removed_record_or_observed_direct_commit_fails_closed(self):
        self.github.append(1)
        old = self.github.main
        self.github.append()
        ledger.allocate_release(self.github, request(1))
        self.github.main = old  # Remove even a direct push seen by the last allocation.
        count = len(self.github.writes)
        with self.assertRaisesRegex(ValueError, "rewritten"):
            ledger.allocate_release(self.github, request(1, 200))
        self.assertEqual(len(self.github.writes), count)

    def test_anchor_only_on_second_parent_is_rejected(self):
        commit = self.github.append(1)
        orphan = "f" * 40
        self.github.commits[orphan] = {"sha": orphan, "parents": []}
        self.github.commits[commit]["parents"] = [{"sha": orphan}, {"sha": ledger.ANCHOR_SHA}]
        with self.assertRaisesRegex(ValueError, "trusted anchor"):
            ledger.allocate_release(self.github, request(1))
        self.assertFalse(self.github.writes)

    def test_api_pagination_is_complete_and_fail_closed_on_limit_or_repetition(self):
        commit = self.github.append(1)
        for number in range(2, 102):
            self.github.prs[number] = pr(number, commit, merged=False)
        self.github.associated[commit] = list(range(1, 102))
        with mock.patch.object(ledger, "MAX_API_PAGES", 1):
            with self.assertRaisesRegex(ValueError, "pagination limit"):
                ledger.allocate_release(self.github, request(1))
        self.assertFalse(self.github.writes)
        self.assertEqual(ledger.allocate_release(self.github, request(1))["version"], "0.1.6")
        self.github.associated[commit] = list(range(1, 101)) * 2
        with self.assertRaisesRegex(ValueError, "changed during pagination"):
            ledger.allocate_release(self.github, request(1))

    def test_ambiguous_pr_same_commit_fails_closed(self):
        commit = self.github.append(1)
        self.github.prs[2] = pr(2, commit)
        self.github.associated[commit] = [1, 2]
        with self.assertRaisesRegex(ValueError, "multiple merged PRs"):
            ledger.allocate_release(self.github, request(1))
        self.assertFalse(self.github.writes)

    def test_selected_pr_event_metadata_and_discovery_must_match(self):
        commit = self.github.append(1)
        with self.assertRaisesRegex(ValueError, "event merge SHA"):
            ledger.allocate_release(self.github, request(1, event="pull_request_target", merge="a" * 40))
        self.github.associated[commit] = []
        with self.assertRaisesRegex(ValueError, "disagree|absent"):
            ledger.allocate_release(self.github, request(1))
        self.assertFalse(self.github.writes)

    def test_run_id_cannot_select_another_pr(self):
        self.github.append(1)
        self.github.append(2)
        ledger.allocate_release(self.github, request(1))
        count = len(self.github.writes)
        with self.assertRaisesRegex(ValueError, "another release"):
            ledger.allocate_release(self.github, request(2))
        self.assertEqual(len(self.github.writes), count)

    def test_publisher_inspection_is_read_only_and_rejects_identity_tampering(self):
        commit = self.github.append(1)
        ledger.allocate_release(self.github, request(1))
        count = len(self.github.writes)
        state = ledger.read_state(self.github)[1]
        for field, value in (("pr_number", 2), ("source_sha", "f" * 40), ("version", "0.1.5"),
                             ("sequence", 7), ("run_id", 200)):
            args = {"pr_number": 1, "source_sha": commit, "version": "0.1.6", "sequence": 6, "run_id": 100}
            args[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                ledger.validate_record(state, **args)
        self.assertEqual(len(self.github.writes), count)

    def test_ledger_history_mutation_of_claim_or_allocation_is_rejected(self):
        for field, value in (("build_run_id", 200), ("pr_number", 2), ("merge_commit", "f" * 40)):
            with self.subTest(field=field):
                github = FakeGitHub()
                github.append(1)
                ledger.allocate_release(github, request(1))
                state = ledger.read_state(github)[1]
                state["entries"][0][field] = value
                github.overwrite_state(state)
                with self.assertRaisesRegex(ValueError, "history changed"):
                    ledger.read_state(github)

    def test_missing_schema_bad_sequence_duplicate_pr_and_duplicate_sha_rejected(self):
        self.github.append(1)
        self.github.append(2)
        ledger.allocate_release(self.github, request(2))
        valid = ledger.read_state(self.github)[1]
        for mutate in (
            lambda s: s.pop("schema"),
            lambda s: s["entries"][0].update(sequence=7),
            lambda s: s["entries"][0].update(version="0.1.5"),
            lambda s: s["entries"][1].update(pr_number=1),
            lambda s: s["entries"][1].update(merge_commit=s["entries"][0]["merge_commit"]),
            lambda s: s["entries"][0].update(build_run_id=True),
            lambda s: s["entries"][0].update(extra="not permitted"),
        ):
            state = copy.deepcopy(valid)
            mutate(state)
            with self.assertRaises(ValueError):
                ledger.validate_state(state)

    def test_more_than_one_page_of_merged_prs_reconciles_all_in_git_order(self):
        for number in range(123, 0, -1):
            self.github.append(number)
        result = ledger.allocate_release(self.github, request(1))
        self.assertEqual(result["version"], "0.1.128")
        state = ledger.read_state(self.github)[1]
        self.assertEqual(len(state["entries"]), 123)
        self.assertEqual(state["entries"][0]["pr_number"], 123)
        self.assertTrue(any(e.startswith("pulls?") and "page=2" in e for e in self.github.reads))

    def test_missing_older_association_fails_before_newer_allocation(self):
        old = self.github.append(1)
        self.github.append(2)
        self.github.associated[old] = []
        with self.assertRaisesRegex(ValueError, "disagree"):
            ledger.allocate_release(self.github, request(2))
        self.assertFalse(self.github.writes)

    def test_canceled_canonical_run_is_not_reassigned_by_schedule(self):
        self.github.append(1)
        ledger.allocate_release(self.github, request(1, 100))
        # Cancellation does not remove a durable reservation or create a new ID.
        count = len(self.github.writes)
        result = ledger.allocate_release(self.github, request(run=200, event="schedule"))
        self.assertEqual((result["should_build"], result["canonical_run_id"]), ("false", ""))
        self.assertEqual(ledger.read_state(self.github)[1]["entries"][0]["build_run_id"], 100)
        self.assertEqual(len(self.github.writes), count)

    def test_success_on_final_cas_attempt_is_verified(self):
        self.github.append(1)
        with mock.patch.object(ledger, "MAX_CAS_ATTEMPTS", 1):
            self.assertEqual(ledger.allocate_release(self.github, request(1))["should_build"], "true")

    def test_main_snapshot_change_retries_before_allocating(self):
        self.github.append(1)
        original = self.github.api
        changed = False
        def api(endpoint, **kwargs):
            nonlocal changed
            result = original(endpoint, **kwargs)
            if endpoint.startswith("commits/") and not changed:
                changed = True
                self.github.append(2)
            return result
        self.github.api = api
        ledger.allocate_release(self.github, request(1))
        self.assertEqual(len(ledger.read_state(self.github)[1]["entries"]), 2)
        self.assertEqual(sum(e[0] == "git/refs" for e in self.github.writes), 1)


class ContextTests(unittest.TestCase):
    def test_closed_merged_target_event_and_main_dispatch(self):
        value = pr(10, "a" * 40)
        result = ledger.request_from_environment(env("pull_request_target"), event(value))
        self.assertEqual((result.pr_number, result.event_merge_sha), (10, "a" * 40))
        result = ledger.request_from_environment(env(), event() | {"inputs": {"pull_request": "10"}})
        self.assertEqual(result.pr_number, 10)
        self.assertIsNone(ledger.request_from_environment(env("schedule"), event()).pr_number)

    def test_no_untrusted_repo_branch_workflow_open_event_or_unmerged_pr(self):
        value = pr(10, "a" * 40)
        for key, invalid in (("GITHUB_REPOSITORY", "attacker/rust_duty"),
                             ("GITHUB_REF", "refs/heads/feature"),
                             ("GITHUB_WORKFLOW_REF", f"{ledger.REPOSITORY}/{ledger.WORKFLOW}@refs/heads/feature"),
                             ("GITHUB_EVENT_NAME", "pull_request"),
                             ("GITHUB_RUN_ID", "1\nmalicious=1"),
                             ("GITHUB_SHA", "a" * 39)):
            environment = env("pull_request_target")
            environment[key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                ledger.request_from_environment(environment, event(value))
        for changes in ({"merged": False}, {"draft": True}, {"state": "open"},
                        {"base": {"ref": "develop", "repo": {"full_name": ledger.REPOSITORY}}}):
            with self.assertRaises(ValueError):
                ledger.request_from_environment(env("pull_request_target"), event(value | changes))
        with self.assertRaises(ValueError):
            ledger.request_from_environment(env("pull_request_target"), event(value) | {"action": "opened"})
        with self.assertRaises(ValueError):
            ledger.request_from_environment(env(), {"repository": {"full_name": "other/repo"}})

    def test_explicit_dispatch_selection_is_bounded_and_matches_input(self):
        with self.assertRaises(ValueError):
            ledger.request_from_environment(env(), event() | {"inputs": {"pull_request": "1"}}, pull_request=2)
        with self.assertRaises(ValueError):
            ledger.request_from_environment(env("schedule"), event(), pull_request=1)
        with self.assertRaises(ValueError):
            ledger.request_from_environment(env(), event() | {"inputs": {"pull_request": "1; shell"}})
        self.assertEqual(ledger.request_from_environment(env(), event(), pull_request=1).pr_number, 1)

    def test_git_data_adapter_uses_explicit_patch_and_never_prints_token_errors(self):
        response = mock.Mock(returncode=0, stdout='{"ok": true}', stderr="")
        with mock.patch.object(ledger.subprocess, "run", return_value=response) as run:
            ledger.GitHub().api(f"git/refs/heads/{ledger.LEDGER_BRANCH}", method="PATCH",
                                payload={"sha": "a" * 40, "force": False})
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("--method") + 1], "PATCH")
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["force"], False)
        response = mock.Mock(returncode=1, stdout="", stderr="a secret token (HTTP 403)")
        with mock.patch.object(ledger.subprocess, "run", return_value=response):
            with self.assertRaises(ledger.APIError) as caught:
                ledger.GitHub().api("git/ref/heads/main")
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
