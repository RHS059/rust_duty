#!/usr/bin/env python3
"""Allocate one immutable PATCH identity for each PR merged into main.

Only the dedicated ledger branch is written. Git Data commits each have exactly
one parent (or none for initialization); non-force ref updates provide CAS. A
lost write response is reconciled by reading the ref again before any retry.
The release workflow must execute this trusted script from main, never PR code.

GitHub's pull-list response has merged_at/merge_commit_sha, but the definitive
merged boolean comes from GET /pulls/{number}. merge_commit_sha means the merge
commit, squash commit, or final rebased commit after merging. We match that SHA
against main's first-parent history, never parse commit messages or timestamps.
See https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request and
https://docs.github.com/en/rest/git/refs#update-a-reference .
"""
from __future__ import annotations

import argparse
import base64
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = "RHS059/rust_duty"
BASE_REF = "refs/heads/main"
WORKFLOW = ".github/workflows/merged-game-release.yml"
LEDGER_BRANCH = "rust-duty-release-ledger"
STATE_FILE = "release-ledger.json"
SCHEMA = "rust-duty-merge-release-ledger/v1"
ANCHOR_SHA = "bfa2042d60b48f9ce076e066b3cd862630d3424e"
CONSUMED_VERSION = "0.1.5"
CONSUMED_SEQUENCE = 5
# Explicit bounds fail closed rather than silently truncating history or pages.
# Discovery and audit are O(main commits + ledger commits); the scheduled
# reconciler must be paused/reworked if repository API quota becomes limiting.
MAX_API_PAGES = 1000
MAX_MAIN_COMMITS = 100000
MAX_LEDGER_COMMITS = 10000
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_CAS_ATTEMPTS = 8


def integer(value, label):
    if type(value) is not int or not 0 < value <= 2**64 - 1:
        raise ValueError(f"invalid {label}")
    return value


def input_integer(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError(f"invalid {label}")
    return integer(int(value), label)


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("invalid exact commit SHA")
    return value


def initial_state():
    return {"schema": SCHEMA, "repository": REPOSITORY, "base_ref": BASE_REF,
            "anchor": ANCHOR_SHA,
            "consumed": {"version": CONSUMED_VERSION, "sequence": CONSUMED_SEQUENCE},
            "observed_main": ANCHOR_SHA, "entries": []}


def validate_state(state):
    template = initial_state()
    if not isinstance(state, dict) or set(state) != set(template):
        raise ValueError("invalid ledger schema")
    for key in ("schema", "repository", "base_ref", "anchor", "consumed"):
        if state[key] != template[key]:
            raise ValueError(f"ledger {key} does not match the trusted release policy")
    if type(state["consumed"]["sequence"]) is not int:
        raise ValueError("invalid consumed release sequence")
    sha(state["observed_main"])
    if not isinstance(state["entries"], list):
        raise ValueError("invalid ledger entries")
    prs, commits, runs = set(), set(), set()
    for index, entry in enumerate(state["entries"], CONSUMED_SEQUENCE + 1):
        if not isinstance(entry, dict) or set(entry) != {
                "pr_number", "merge_commit", "version", "sequence", "build_run_id"}:
            raise ValueError("invalid ledger entry fields")
        integer(entry["pr_number"], "PR number")
        sha(entry["merge_commit"])
        integer(entry["sequence"], "release sequence")
        if entry["sequence"] != index or entry["version"] != f"0.1.{index}":
            raise ValueError("ledger versions and sequences must be contiguous PATCH increments")
        if entry["pr_number"] in prs or entry["merge_commit"] in commits:
            raise ValueError("duplicate ledger PR or merge SHA")
        prs.add(entry["pr_number"])
        commits.add(entry["merge_commit"])
        if entry["build_run_id"] is not None:
            integer(entry["build_run_id"], "canonical build run id")
            if entry["build_run_id"] in runs:
                raise ValueError("one build run cannot own multiple releases")
            runs.add(entry["build_run_id"])
    return state


def validate_transition(previous, current):
    validate_state(previous)
    validate_state(current)
    old, new = previous["entries"], current["entries"]
    if len(new) < len(old):
        raise ValueError("ledger history removed allocations")
    for before, after in zip(old, new):
        if any(before[key] != after[key] for key in before if key != "build_run_id"):
            raise ValueError("ledger history changed an immutable allocation")
        if before["build_run_id"] is not None and before["build_run_id"] != after["build_run_id"]:
            raise ValueError("ledger history changed a canonical build run")
    return current


def validate_record(state, pr_number, source_sha, version, sequence, run_id):
    """Read-only publisher guard. Every argument must match the canonical entry."""
    validate_state(state)
    integer(pr_number, "PR number")
    sha(source_sha)
    integer(sequence, "release sequence")
    integer(run_id, "canonical build run id")
    expected = {"pr_number": pr_number, "merge_commit": source_sha,
                "version": version, "sequence": sequence, "build_run_id": run_id}
    entry = next((e for e in state["entries"] if e["pr_number"] == pr_number), None)
    if entry != expected:
        raise ValueError("release identity differs from its canonical merged-PR ledger record")
    return copy.deepcopy(entry)


class APIError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class GitHub:
    """Use existing gh authentication. Tokens are never read or printed here."""
    def __init__(self):
        self._immutable = {}

    def api(self, endpoint, *, payload=None, method=None, missing_ok=False):
        cacheable = payload is None and re.fullmatch(r"git/(commits|trees|blobs)/[0-9a-f]{40}", endpoint)
        if cacheable and endpoint in self._immutable:
            return copy.deepcopy(self._immutable[endpoint])
        args = ["gh", "api", f"repos/{REPOSITORY}/{endpoint}",
                "-H", "Accept: application/vnd.github+json"]
        if method or payload is not None:
            args += ["--method", method or "POST"]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(args, input=None if payload is None else json.dumps(payload),
                                text=True, capture_output=True, check=False)
        if result.returncode:
            match = re.search(r"\(HTTP (\d{3})\)", result.stderr)
            status = int(match.group(1)) if match else None
            if missing_ok and status == 404:
                return None
            # Do not echo arbitrary API text, URLs or authentication diagnostics.
            raise APIError(f"GitHub API request failed ({status or 'unknown status'})", status)
        try:
            value = json.loads(result.stdout)
            if cacheable:
                self._immutable[endpoint] = copy.deepcopy(value)
            return value
        except (ValueError, TypeError) as error:
            raise APIError("GitHub API returned invalid JSON") from error


def ref_sha(value, ref):
    if not isinstance(value, dict) or value.get("ref") != ref:
        raise ValueError("unexpected Git ref response")
    if not isinstance(value.get("object"), dict) or value["object"].get("type") != "commit":
        raise ValueError("Git ref does not name a commit")
    return sha(value["object"].get("sha"))


def commit_data(github, commit):
    value = github.api(f"git/commits/{sha(commit)}")
    if not isinstance(value, dict) or value.get("sha") != commit:
        raise ValueError("Git commit response SHA mismatch")
    parents = value.get("parents")
    if not isinstance(parents, list):
        raise ValueError("invalid Git commit parents")
    for parent in parents:
        if not isinstance(parent, dict):
            raise ValueError("invalid Git commit parent")
        sha(parent.get("sha"))
    return value


def state_at_commit(github, commit):
    value = commit_data(github, commit)
    if len(value["parents"]) > 1:
        raise ValueError("ledger history must be a linear orphan-rooted branch")
    tree_sha = sha(value.get("tree", {}).get("sha"))
    tree = github.api(f"git/trees/{tree_sha}")
    if (not isinstance(tree, dict) or tree.get("sha") != tree_sha
            or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list)
            or len(tree["tree"]) != 1):
        raise ValueError("ledger must contain exactly one untruncated state file")
    node = tree["tree"][0]
    if (node.get("path") != STATE_FILE or node.get("type") != "blob"
            or node.get("mode") != "100644"):
        raise ValueError("ledger has unexpected files or file mode")
    blob_sha = sha(node.get("sha"))
    blob = github.api(f"git/blobs/{blob_sha}")
    if (not isinstance(blob, dict) or blob.get("sha") != blob_sha
            or blob.get("encoding") != "base64" or type(blob.get("size")) is not int
            or not 0 <= blob["size"] <= MAX_STATE_BYTES):
        raise ValueError("invalid ledger blob")
    try:
        raw = base64.b64decode("".join(blob["content"].split()), validate=True)
        if len(raw) != blob["size"]:
            raise ValueError("ledger blob size mismatch")
        state = json.loads(raw, object_pairs_hook=unique_json_object)
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValueError("invalid ledger JSON") from error
    return validate_state(state), [p["sha"] for p in value["parents"]]


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field in ledger or event")
        result[key] = value
    return result


def read_state(github):
    """Return (ledger commit SHA or None, state), with no remote writes.

    Verify the whole ledger chain so overwritten run IDs, removed allocations,
    source-file trees, and a non-orphan initialization cannot pass inspection.
    """
    ref = f"refs/heads/{LEDGER_BRANCH}"
    value = github.api(f"git/ref/heads/{LEDGER_BRANCH}", missing_ok=True)
    if value is None:
        return None, initial_state()
    head = ref_sha(value, ref)
    cursor, seen, later, latest = head, set(), None, None
    for _ in range(MAX_LEDGER_COMMITS):
        if cursor in seen:
            raise ValueError("cycle in ledger history")
        seen.add(cursor)
        current, parents = state_at_commit(github, cursor)
        if latest is None:
            latest = current
        if later is not None:
            validate_transition(current, later)
        if not parents:
            validate_transition(initial_state(), current)
            return head, latest
        cursor, later = parents[0], current
    raise ValueError("ledger history limit reached; refusing truncated validation")


def main_history(github, head):
    """Oldest-to-newest first-parent commits after anchor, including direct pushes."""
    cursor, descending, seen = sha(head), [], set()
    for _ in range(MAX_MAIN_COMMITS):
        if cursor == ANCHOR_SHA:
            return list(reversed(descending))
        if cursor in seen:
            raise ValueError("cycle in main history")
        seen.add(cursor)
        value = commit_data(github, cursor)
        descending.append(cursor)
        if not value["parents"]:
            raise ValueError("main no longer descends from the trusted anchor")
        cursor = value["parents"][0]["sha"]
    raise ValueError("main ancestry limit reached; refusing truncated history")


def paginated(github, endpoint):
    seen = set()
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, MAX_API_PAGES + 1):
        values = github.api(f"{endpoint}{separator}per_page=100&page={page}")
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("invalid paginated PR listing")
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("invalid PR listing entry")
            number = integer(value.get("number"), "PR number")
            if number in seen:
                raise ValueError("PR listing changed during pagination")
            seen.add(number)
            yield value
        if len(values) < 100:
            return
    raise ValueError("PR pagination limit reached; refusing incomplete allocation")


def merged_pr(value, number=None):
    if not isinstance(value, dict):
        raise ValueError("invalid PR response")
    integer(value.get("number"), "PR number")
    if number is not None and value["number"] != number:
        raise ValueError("PR response number mismatch")
    base = value.get("base", {})
    if (value.get("state") != "closed" or value.get("merged") is not True
            or not value.get("merged_at") or value.get("draft") is not False
            or base.get("ref") != "main" or base.get("repo", {}).get("full_name") != REPOSITORY):
        raise ValueError("release requires a closed, merged, non-draft PR into this repository's main")
    sha(value.get("merge_commit_sha"))
    return value


def discover_merges(github, history):
    """Query PR metadata for each main commit, with complete API pagination.

    Commit-associated PRs avoids closed-list pagination shifting when unrelated
    old PRs close mid-scan. It also covers merge, squash and the final rebase SHA.
    GitHub can associate unmerged PRs or multiple commits with a PR; only its
    verified final merge_commit_sha is allocated. Direct commits allocate nothing.
    """
    by_commit, by_pr = {}, {}
    details = {}
    for commit in history:
        for summary in paginated(github, f"commits/{commit}/pulls"):
            number = summary["number"]
            if number not in details:
                details[number] = github.api(f"pulls/{number}")
            value = details[number]
            if not isinstance(value, dict) or value.get("number") != number:
                raise ValueError("associated PR detail mismatch")
            base = value.get("base", {})
            if (value.get("state") != "closed" or value.get("merged") is not True
                    or value.get("draft") is not False or base.get("ref") != "main"
                    or base.get("repo", {}).get("full_name") != REPOSITORY):
                continue
            merged_pr(value, number)
            if value["merge_commit_sha"] != commit:
                continue
            if commit in by_commit and by_commit[commit] != number:
                raise ValueError("multiple merged PRs claim one main commit")
            if number in by_pr and by_pr[number] != commit:
                raise ValueError("one PR claims multiple main commits")
            by_commit[commit], by_pr[number] = number, commit
    # Independent full listing catches incomplete/eventually-consistent commit
    # associations. Conversely, association discovery detects a shifted closed
    # list that omitted a row. We require agreement rather than trust either gap.
    listed = {}
    ancestry = set(history)
    for summary in paginated(github, "pulls?state=closed&base=main&sort=created&direction=asc"):
        number = summary["number"]
        if not summary.get("merged_at"):
            continue
        commit = sha(summary.get("merge_commit_sha"))
        if commit not in ancestry:
            continue
        value = details.get(number)
        if value is None:
            value = github.api(f"pulls/{number}")
        if (value.get("draft") is not False or value.get("base", {}).get("ref") != "main"
                or value.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY):
            continue
        merged_pr(value, number)
        if value["merge_commit_sha"] != commit:
            raise ValueError("closed PR listing changed during merge discovery")
        if commit in listed:
            raise ValueError("multiple merged PRs claim one main commit")
        listed[commit] = number
    if listed != by_commit:
        raise ValueError("closed PR listing and commit associations disagree; retry discovery")
    return [(by_commit[commit], commit) for commit in history if commit in by_commit]


@dataclass(frozen=True)
class Request:
    event_name: str
    run_id: int
    workflow_sha: str
    pr_number: int | None = None
    event_merge_sha: str | None = None


def request_from_environment(env=None, event=None, *, pull_request=None):
    env = os.environ if env is None else env
    if event is None:
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"),
                           object_pairs_hook=unique_json_object)
    if (env.get("GITHUB_REPOSITORY") != REPOSITORY or not isinstance(event, dict)
            or event.get("repository", {}).get("full_name") != REPOSITORY
            or env.get("GITHUB_REF") != BASE_REF
            or env.get("GITHUB_WORKFLOW_REF") != f"{REPOSITORY}/{WORKFLOW}@{BASE_REF}"):
        raise ValueError("release allocation requires this repository's trusted main workflow")
    name = env.get("GITHUB_EVENT_NAME")
    run_id = input_integer(env.get("GITHUB_RUN_ID"), "run id")
    workflow_sha = sha(env.get("GITHUB_SHA"))
    if name == "pull_request_target":
        if pull_request is not None or event.get("action") != "closed":
            raise ValueError("only closed merged-PR events may allocate releases")
        value = merged_pr(event.get("pull_request"))
        if event.get("number") != value["number"]:
            raise ValueError("event PR number mismatch")
        return Request(name, run_id, workflow_sha, value["number"], value["merge_commit_sha"])
    if name not in ("workflow_dispatch", "schedule"):
        raise ValueError("unsupported release allocation event")
    selected = event.get("inputs", {}).get("pull_request") if name == "workflow_dispatch" else None
    if selected in (None, ""):
        selected = None
    else:
        selected = input_integer(selected, "selected PR number")
    if pull_request is not None:
        integer(pull_request, "selected PR number")
        if name != "workflow_dispatch" or selected is not None and selected != pull_request:
            raise ValueError("explicit PR selection differs from trusted dispatch input")
        selected = pull_request
    return Request(name, run_id, workflow_sha, selected)


def write_state(github, expected_head, previous, state):
    """Create immutable objects, then CAS the dedicated branch without force."""
    validate_transition(previous, state)
    content = json.dumps(state, indent=2, sort_keys=True) + "\n"
    if len(content.encode()) > MAX_STATE_BYTES:
        raise ValueError("ledger state exceeds safety limit")
    tree = github.api("git/trees", payload={"tree": [
        {"path": STATE_FILE, "mode": "100644", "type": "blob", "content": content}]})
    tree_sha = sha(tree.get("sha"))
    commit = github.api("git/commits", payload={"message": "Record immutable merged-PR release identities",
                        "tree": tree_sha, "parents": [] if expected_head is None else [sha(expected_head)]})
    commit_sha = sha(commit.get("sha"))
    if expected_head is None:
        github.api("git/refs", payload={"ref": f"refs/heads/{LEDGER_BRANCH}", "sha": commit_sha})
    else:
        github.api(f"git/refs/heads/{LEDGER_BRANCH}", method="PATCH",
                   payload={"sha": commit_sha, "force": False})
    return commit_sha


def outputs(entry, run_id):
    if entry is None:
        return {"version": "", "release_sequence": "", "commit_sha": "", "pull_request": "",
                "should_build": "false", "canonical_run_id": ""}
    return {"version": entry["version"], "release_sequence": str(entry["sequence"]),
            "commit_sha": entry["merge_commit"], "pull_request": str(entry["pr_number"]),
            "should_build": "true" if entry["build_run_id"] == run_id else "false",
            "canonical_run_id": str(entry["build_run_id"] or "")}


def allocate_release(github, request):
    integer(request.run_id, "run id")
    sha(request.workflow_sha)
    if request.event_name not in ("pull_request_target", "workflow_dispatch", "schedule"):
        raise ValueError("unsupported release event")
    if request.pr_number is not None:
        integer(request.pr_number, "PR number")
    if request.event_name == "pull_request_target" and (
            request.pr_number is None or request.event_merge_sha is None):
        raise ValueError("merged-PR event identity is missing")
    if request.event_name == "schedule" and request.pr_number is not None:
        raise ValueError("scheduled reconciliation cannot select an arbitrary PR")
    for _ in range(MAX_CAS_ATTEMPTS):
        ledger_head, state = read_state(github)
        main_head = ref_sha(github.api("git/ref/heads/main"), BASE_REF)
        history = main_history(github, main_head)
        ancestry = {ANCHOR_SHA, *history}
        if state["observed_main"] not in ancestry or request.workflow_sha not in ancestry:
            raise ValueError("main was rewritten or the workflow SHA is not on trusted main")
        if request.pr_number is not None:
            selected_pr = merged_pr(github.api(f"pulls/{request.pr_number}"), request.pr_number)
            selected_sha = selected_pr["merge_commit_sha"]
            if selected_sha not in history:
                raise ValueError("selected merge is not on main after the trusted anchor")
            if request.event_merge_sha is not None and request.event_merge_sha != selected_sha:
                raise ValueError("event merge SHA differs from GitHub's merged PR")
        merges = discover_merges(github, history)
        # A merge during discovery invalidates its snapshot; never assign from it.
        if ref_sha(github.api("git/ref/heads/main"), BASE_REF) != main_head:
            continue
        if [(e["pr_number"], e["merge_commit"]) for e in state["entries"]] != merges[:len(state["entries"])]:
            raise ValueError("ledger differs from authoritative main merge order")
        if request.pr_number is not None and request.pr_number not in {number for number, _ in merges}:
            raise ValueError("selected merged PR is absent from complete commit-associated discovery")
        own_run = next((e for e in state["entries"] if e["build_run_id"] == request.run_id), None)
        existing = next((e for e in state["entries"] if e["pr_number"] == request.pr_number), None)
        if own_run is not None:
            if request.pr_number is not None and own_run["pr_number"] != request.pr_number:
                raise ValueError("build run already owns another release")
            return outputs(own_run, request.run_id)
        if existing is not None and existing["build_run_id"] is not None:
            # Independent duplicate runs must never overwrite/rebuild partial work.
            return outputs(existing, request.run_id)
        updated = copy.deepcopy(state)
        for number, commit in merges[len(state["entries"]):]:
            sequence = CONSUMED_SEQUENCE + len(updated["entries"]) + 1
            updated["entries"].append({"pr_number": number, "merge_commit": commit,
                "version": f"0.1.{sequence}", "sequence": sequence, "build_run_id": None})
        selected = next((e for e in updated["entries"] if e["pr_number"] == request.pr_number), None)
        if request.pr_number is None:
            selected = next((e for e in updated["entries"] if e["build_run_id"] is None), None)
        if selected is None:
            return outputs(None, request.run_id)
        selected["build_run_id"] = request.run_id
        updated["observed_main"] = main_head
        try:
            write_state(github, ledger_head, state, updated)
        except APIError as error:
            if error.status not in (None, 409, 422, 500, 502, 503, 504):
                raise
            # A concurrent writer or lost reply is resolved at the top of the
            # loop from the actual ref; no repeat ref write without that read.
            continue
        # Verify the durable ref, not merely the object-creation response.
        durable_head, durable = read_state(github)
        if durable_head is not None:
            entry = next((e for e in durable["entries"] if e["pr_number"] == selected["pr_number"]), None)
            if entry is not None and entry["build_run_id"] is not None:
                if any(entry[key] != selected[key] for key in entry if key != "build_run_id"):
                    raise ValueError("durable ledger allocation changed after CAS")
                current_head = ref_sha(github.api("git/ref/heads/main"), BASE_REF)
                if current_head != main_head and main_head not in main_history(github, current_head):
                    raise ValueError("main was rewritten during ledger allocation")
                return outputs(entry, request.run_id)
    raise ValueError("ledger/main changed too often; retry the same workflow run")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", type=int, help="merged PR selected by trusted main dispatch")
    args = parser.parse_args()
    request = request_from_environment(pull_request=args.pull_request)
    result = allocate_release(GitHub(), request)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            for key, value in result.items():
                if not re.fullmatch(r"[A-Za-z0-9_.]*", value):
                    raise ValueError("unsafe workflow output")
                stream.write(f"{key}={value}\n")
    print(json.dumps(result, sort_keys=True))
    if result["should_build"] == "false" and result["canonical_run_id"]:
        print(f"Release already belongs to run {result['canonical_run_id']}; rerun that original run to recover.")


if __name__ == "__main__":
    main()
