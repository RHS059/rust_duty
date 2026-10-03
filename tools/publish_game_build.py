#!/usr/bin/env python3
"""Publish same-run complete game artifacts, without rebuilding or mutable assets.

Must run under build.yml's rust-duty-release-channel concurrency lock. The only
writes are creating this run's draft, adding missing identical assets, and making
that complete draft public. Existing public releases and assets are never edited.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from urllib.parse import urlencode

import build_identity
import package_game
import release_update

REPOSITORY = build_identity.REPOSITORY
PROVENANCE = "SOURCE_PROVENANCE.json"
RECOVERY_RELEASE_ID = 402704474
RECOVERY_EMPTY_ORPHAN_ID = 402709395
RECOVERY_PROVENANCE_SHA256 = "7e991ac6d57e96a38959108bbebfca63dfc6516749956e1a621ab078a933185e"
RECOVERY_EXECUTION_BRANCH = "aella-release-recovery/0.1.5"
RECOVERY_RUN_ID = 37154246170
RECOVERY_COMMIT = "eb886edb9ed31ad6feae13541c4e34aa70362f2f"
MAX_API_PAGES = 10


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def deterministic_zip(source, destination, executable):
    """ZIP bytes do not depend on download times, host permissions or run attempts."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(Path(source).rglob("*")):
            if path.is_symlink():
                raise ValueError("symlink in staged complete game")
            if not path.is_file():
                continue
            name = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name == executable else 0o100644) << 16
            with path.open("rb") as src, archive.open(info, "w", force_zip64=True) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)


def prepare(tested, output, identity):
    """Curate both platforms through the same strict allowlist as game builds."""
    tested, output = Path(tested), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("release preparation requires a fresh output directory")
    verified = {platform: build_identity.verify(tested / platform, platform, identity)
                for platform in build_identity.TARGETS}
    output.mkdir(parents=True)
    provenance = {"schema": "rust-duty-game-release/v1", **identity,
                  "artifacts": {}, "assets": {}}
    with tempfile.TemporaryDirectory(prefix=".game-release-", dir=output.parent) as directory:
        for platform, (target, executable, label, _) in build_identity.TARGETS.items():
            source = tested / platform
            payload = Path(directory) / platform / "update"
            complete = Path(directory) / platform / "complete"
            package_game.stage(source, executable, payload, update=True, require_generated=True)
            package_game.stage(source, executable, complete, require_generated=True)
            # Artifact transport loses executable bits. Normalize explicitly so reruns
            # and the Windows-on-Linux packaging produce the same bundle and ZIP bytes.
            for staged in (payload, complete):
                for path in staged.rglob("*"):
                    if path.is_file():
                        path.chmod(0o755 if path.relative_to(staged).as_posix() == executable else 0o644)
            release_update.prepare(argparse.Namespace(
                input=payload, output=output, version=identity["version"], sequence=identity["sequence"],
                target=target, entrypoint=executable, previous=None, previous_version=None))
            release_update.verify_manifest(argparse.Namespace(
                manifest=output / f"update-{target}.json", assets_dir=output,
                version=identity["version"], target=target, bundle_only=False))
            deterministic_zip(complete, output / f'Rust-Duty-{identity["version"]}-{label}-x64.zip', executable)
            # A migration executable stays available, but no separate launcher build
            # or obsolete release-plan branch can hold up an in-game update.
            migration = "vector-range.exe" if platform == "windows" else "vector-range-linux-x64"
            shutil.copy2(payload / executable, output / migration)
            provenance["artifacts"][platform] = {
                "name": f"vector-range-{platform}-x64", "identity": verified[platform]}
    for path in sorted(output.iterdir()):
        provenance["assets"][path.name] = release_update.asset(path)
    write_json(output / PROVENANCE, provenance)
    return provenance


class GitHub:
    """Use the runner's existing GitHub CLI authentication, never persist tokens."""
    def api(self, endpoint, *, payload=None, missing_ok=False):
        args = ["gh", "api", f"repos/{REPOSITORY}/{endpoint}"]
        if payload is not None:
            args += ["--method", "PATCH" if endpoint.startswith("releases/") else "POST", "--input", "-"]
        result = subprocess.run(args, input=None if payload is None else json.dumps(payload),
                                text=True, capture_output=True, check=False)
        if result.returncode:
            if missing_ok and "(HTTP 404)" in result.stderr:
                return None
            raise RuntimeError(f"GitHub API request failed: {result.stderr.strip()}")
        return json.loads(result.stdout)

    def download(self, asset, destination):
        if type(asset.get("id")) is not int or asset["id"] < 1:
            raise ValueError("invalid release asset id")
        with Path(destination).open("wb") as stream:
            subprocess.run(["gh", "api", f'repos/{REPOSITORY}/releases/assets/{asset["id"]}',
                            "-H", "Accept: application/octet-stream"], stdout=stream, check=True)

    def upload(self, release, path):
        # Draft tags are not discoverable through releases/tags or gh release
        # upload. Address only this already-verified release ID's upload endpoint.
        url = upload_url(release, path.name)
        result = subprocess.run(["gh", "api", url, "--method", "POST",
                                 "-H", "Content-Type: application/octet-stream",
                                 "-H", f"Content-Length: {path.stat().st_size}",
                                 "--input", str(path)], text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Release asset upload failed: {result.stderr.strip()}")
        verify_remote_asset(self, json.loads(result.stdout), path)


def upload_url(release, name):
    number = release.get("id")
    if type(number) is not int or number < 1:
        raise ValueError("invalid existing release id")
    base = f"https://uploads.github.com/repos/{REPOSITORY}/releases/{number}/assets"
    if release.get("upload_url") not in (base, base + "{?name,label}"):
        raise ValueError("release upload URL does not match its trusted repository and id")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("invalid upload asset name")
    return base + "?" + urlencode({"name": name})


def find_release(github, tag, *, required_id=None, allow_empty_orphan=False):
    """Authenticated release listing includes drafts; by-tag 404 proves nothing."""
    matches = []
    for page in range(1, MAX_API_PAGES + 1):
        values = github.api(f"releases?per_page=100&page={page}")
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("invalid release listing")
        matches.extend(item for item in values if item.get("tag_name") == tag)
        if len(values) < 100:
            break
    else:
        raise ValueError("release discovery pagination limit reached; refusing creation")
    if not matches:
        if required_id is not None:
            raise ValueError("required recovery draft is missing; creation is forbidden")
        return None
    if len(matches) > 1:
        ids = [item.get("id") for item in matches]
        if (not allow_empty_orphan or required_id != RECOVERY_RELEASE_ID
                or len(ids) != 2 or set(ids) != {RECOVERY_RELEASE_ID, RECOVERY_EMPTY_ORPHAN_ID}):
            raise ValueError("duplicate releases for the exact version tag; refusing publication")
        original = github.api(f"releases/{RECOVERY_RELEASE_ID}")
        orphan = github.api(f"releases/{RECOVERY_EMPTY_ORPHAN_ID}")
        if (orphan.get("id") != RECOVERY_EMPTY_ORPHAN_ID or orphan.get("tag_name") != tag
                or orphan.get("draft") is not True or orphan.get("prerelease") is not False
                or orphan.get("target_commitish") != original.get("target_commitish")
                or orphan.get("body") != original.get("body") or release_assets(orphan)):
            raise ValueError("known duplicate is not the unchanged empty draft; refusing recovery")
        matches = [original]
    number = matches[0].get("id")
    if type(number) is not int or number < 1 or (required_id is not None and number != required_id):
        raise ValueError("release id differs from required recovery draft")
    result = github.api(f"releases/{number}")
    if result.get("id") != number or result.get("tag_name") != tag:
        raise ValueError("release identity changed after discovery")
    return result


def recovery_identity(github, tested, release_id, source_run_id, source_commit, env=None):
    """Allow only the named failed publication's already-tested original artifacts."""
    env = os.environ if env is None else env
    branch = "aella/automatic-game-updates-r1"
    if (release_id, source_run_id, source_commit) != (RECOVERY_RELEASE_ID, RECOVERY_RUN_ID, RECOVERY_COMMIT):
        raise ValueError("recovery must name the explicitly authorized existing draft and source run")
    if (env.get("GITHUB_REPOSITORY") != REPOSITORY
            or env.get("GITHUB_REF") != "refs/heads/" + RECOVERY_EXECUTION_BRANCH
            or env.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch")):
        raise ValueError("recovery requires the authorized repository and branch")
    run = github.api(f"actions/runs/{source_run_id}")
    if (run.get("id") != source_run_id or run.get("head_sha") != source_commit
            or run.get("head_branch") != branch or run.get("event") != "push"
            or run.get("path") != build_identity.WORKFLOW
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("status") != "completed" or type(run.get("run_number")) is not int):
        raise ValueError("original build run provenance or completion could not be verified")
    jobs = []
    for page in range(1, MAX_API_PAGES + 1):
        response = github.api(f"actions/runs/{source_run_id}/jobs?filter=all&per_page=100&page={page}")
        entries = response.get("jobs")
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError("invalid original build job listing")
        jobs.extend(entries)
        if len(entries) < 100:
            break
    else:
        raise ValueError("original build jobs exceeded pagination limit")
    for name in ("ubuntu-latest", "windows-latest"):
        matching = [job for job in jobs if job.get("name") == name
                    and job.get("run_id") == source_run_id and job.get("head_sha") == source_commit
                    and job.get("status") == "completed" and job.get("conclusion") == "success"]
        if not matching:
            raise ValueError(f"original complete build matrix job did not succeed: {name}")
    original = {
        "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_NUMBER": str(run["run_number"]),
        "GITHUB_RUN_ID": str(source_run_id), "GITHUB_SHA": source_commit,
        "GITHUB_REF_NAME": branch, "GITHUB_REF": "refs/heads/" + branch,
        "GITHUB_EVENT_NAME": "push", "RUST_DUTY_BUILD_VERSION": "0.1.5",
        "RUST_DUTY_BUILD_RESULT": "success",
    }
    identity = build_identity.context(original, publication=True)
    for platform in build_identity.TARGETS:
        build_identity.verify(Path(tested) / platform, platform, identity)
    existing = find_release(github, "v0.1.5", required_id=release_id, allow_empty_orphan=True)
    if (existing.get("target_commitish") != source_commit or existing.get("body") != release_notes(identity)
            or existing.get("prerelease") is not False):
        raise ValueError("known recovery draft does not match original source and provenance")
    return identity


def release_assets(release):
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("release assets missing")
    indexed = {}
    for asset in assets:
        name = asset.get("name")
        if not isinstance(name, str) or name in indexed:
            raise ValueError("duplicate or invalid release asset name")
        indexed[name] = asset
    return indexed


def latest_identity(github):
    latest = github.api("releases/latest", missing_ok=True)
    if latest is None:
        return None
    if latest.get("draft") is not False or latest.get("prerelease") is not False:
        raise ValueError("latest channel must be a public stable release")
    assets = release_assets(latest)
    manifests = []
    with tempfile.TemporaryDirectory(prefix="latest-game-channel-") as directory:
        for target, executable, _, _ in build_identity.TARGETS.values():
            name = f"update-{target}.json"
            item = assets.get(name)
            if (not item or item.get("state") != "uploaded" or type(item.get("size")) is not int
                    or not 0 < item["size"] <= 1024 * 1024):
                raise ValueError("latest release lacks both complete update manifests")
            path = Path(directory) / name
            github.download(item, path)
            manifest = release_update.verify_manifest(argparse.Namespace(
                manifest=path, assets_dir=None, version=None, target=target, bundle_only=True))
            if manifest["entrypoint"] != executable or latest["tag_name"] != f'v{manifest["version"]}':
                raise ValueError("latest manifest does not match release tag or executable")
            bundle = assets.get(manifest["bundle"]["name"])
            if (not bundle or bundle.get("state") != "uploaded"
                    or bundle.get("size") != manifest["bundle"]["size"]):
                raise ValueError("latest release lacks complete update bundle")
            manifests.append(manifest)
    first, second = manifests
    if (first["version"], first["sequence"]) != (second["version"], second["sequence"]):
        raise ValueError("latest platform update identities disagree")
    return {"version": first["version"], "sequence": first["sequence"]}


def publication_order(candidate, latest):
    if latest is None:
        return "newer"
    version = release_update.stable_version(candidate["version"])
    old = release_update.stable_version(latest["version"])
    sequence, previous = candidate["sequence"], latest["sequence"]
    if version == old and sequence == previous:
        return "same"
    if version < old and sequence < previous:
        return "superseded"
    if version > old and sequence > previous:
        return "newer"
    raise ValueError("release version/sequence conflict; refusing rollback or replay")


def release_notes(identity):
    title = (f'Complete game build {identity["version"]} from merged PR #{identity["merge"]["pull_request"]}.'
             if "merge" in identity else f'Explicitly authorized one-time complete game build {identity["version"]}.')
    return (title + '\n\n'
            f'Source: {identity["source"]["commit"]}\n'
            f'Branch: {identity["source"]["branch"]}\n'
            f'Build: {identity["source"]["run_url"]}\n'
            f'Update sequence: {identity["sequence"]}\n\n'
            'Windows and Linux checks, authored-asset validation and native Linux gameplay '
            'capture gates passed before publication. Full managed updates and complete '
            'game ZIPs contain only the approved packaging allowlist. User settings and '
            'private soldier assets are excluded from managed updates.\n\n'
            'Trust: RHS059/rust_duty over GitHub HTTPS, with payload sizes and SHA-256. '
            'There is no independent signing key. See SOURCE_PROVENANCE.json for exact '
            'build identities and asset hashes.')


def verify_remote_asset(github, remote, local):
    verify_remote_record(github, remote, release_update.asset(local))


def verify_remote_record(github, remote, expected):
    if (set(expected) != {"name", "size", "sha256"}
            or not isinstance(expected["name"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}", expected["name"])
            or type(expected["size"]) is not int or not 0 < expected["size"] <= release_update.MAX_SIZE
            or not isinstance(expected["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
        raise ValueError("invalid expected immutable asset record")
    if (remote.get("name") != expected["name"] or remote.get("state") != "uploaded"
            or remote.get("size") != expected["size"]):
        raise ValueError(f'immutable asset differs: {expected["name"]}')
    digest = remote.get("digest")
    if digest is not None:
        if digest != "sha256:" + expected["sha256"]:
            raise ValueError(f'immutable asset digest differs: {expected["name"]}')
    else:
        # Older GitHub responses can omit a server digest. Download and hash rather
        # than trusting a same-length file or overwriting an uncertain upload.
        with tempfile.TemporaryDirectory(prefix="verify-release-asset-") as directory:
            downloaded = Path(directory) / expected["name"]
            github.download(remote, downloaded)
            if downloaded.stat().st_size != expected["size"] or release_update.sha(downloaded) != expected["sha256"]:
                raise ValueError(f'immutable asset bytes differ: {expected["name"]}')


def verify_tag(github, tag, commit, *, required=False):
    reference = github.api(f"git/ref/tags/{tag}", missing_ok=not required)
    if reference is None:
        return
    obj = reference.get("object", {})
    if obj.get("type") != "commit" or obj.get("sha") != commit:
        raise ValueError("release tag does not point to this exact source commit")


def publish(github, output, identity, *, recovery_release_id=None):
    output = Path(output)
    tag = "v" + identity["version"]
    notes = release_notes(identity)
    expected = {path.name: path for path in output.iterdir() if path.is_file()}
    if PROVENANCE not in expected or len(expected) != 9:
        raise ValueError("incomplete one-time release asset set")
    latest = latest_identity(github)
    order = publication_order(identity, latest)
    if order == "superseded" and "merge" not in identity:
        return {"status": "superseded", "version": identity["version"], "latest": latest}
    existing = find_release(github, tag, required_id=recovery_release_id,
                            allow_empty_orphan=recovery_release_id is not None)
    verify_tag(github, tag, identity["source"]["commit"])
    if existing is None:
        if recovery_release_id is not None:
            raise ValueError("recovery cannot create a release")
        if order == "same":
            raise ValueError("latest identity exists without its expected release")
        existing = github.api("releases", payload={
            "tag_name": tag, "target_commitish": identity["source"]["commit"],
            "name": f'Rust Duty {identity["version"]}', "body": notes,
            "draft": True, "prerelease": False, "make_latest": "false"})
    if (existing.get("tag_name") != tag or existing.get("body") != notes
            or existing.get("target_commitish") != identity["source"]["commit"]
            or existing.get("prerelease") is not False):
        raise ValueError("existing release identity differs; refusing replacement")
    remote = release_assets(existing)
    if set(remote) - set(expected):
        raise ValueError("existing release has unexpected assets; refusing replacement")
    for name, asset in remote.items():
        verify_remote_asset(github, asset, expected[name])
    if recovery_release_id is not None:
        missing = set(expected) - set(remote)
        if not missing.issubset({"vector-range.exe", "vector-range-linux-x64"}):
            raise ValueError("recovery may only add the two known missing migration executables")
    if existing.get("draft") is False:
        if set(remote) != set(expected):
            raise ValueError("published release is incomplete; refusing mutation")
        verify_tag(github, tag, identity["source"]["commit"], required=True)
        return {"status": "already-published", "version": identity["version"], "url": existing["html_url"]}
    if existing.get("draft") is not True:
        raise ValueError("unknown release state")
    for name in sorted(set(expected) - set(remote)):
        github.upload(existing, expected[name])
    complete = github.api(f'releases/{existing["id"]}')
    remote = release_assets(complete)
    if set(remote) != set(expected):
        raise ValueError("uploaded release asset set is incomplete")
    for name, asset in remote.items():
        verify_remote_asset(github, asset, expected[name])
    # Check once again immediately before the atomic visibility/latest change.
    order = publication_order(identity, latest_identity(github))
    if order != "newer" and not (order == "superseded" and "merge" in identity):
        if order == "superseded":
            return {"status": "superseded-draft", "version": identity["version"]}
        raise ValueError("channel changed during draft publication")
    verify_tag(github, tag, identity["source"]["commit"])
    promote = order == "newer"
    published = github.api(f'releases/{existing["id"]}', payload={"draft": False, "make_latest": "true" if promote else "false"})
    if published.get("draft") is not False or published.get("tag_name") != tag:
        raise ValueError("public release visibility was not confirmed")
    verify_tag(github, tag, identity["source"]["commit"], required=True)
    expected_order = "same" if promote else "superseded"
    if publication_order(identity, latest_identity(github)) != expected_order:
        raise ValueError("published release channel changed unexpectedly")
    return {"status": "published", "version": identity["version"], "url": published["html_url"]}


def recover(github, tested, output, identity, release_id):
    """Complete only the pinned original draft; never repack/rebuild large assets."""
    if release_id != RECOVERY_RELEASE_ID:
        raise ValueError("fast recovery requires the original authorized release id")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("recovery requires a fresh local output directory")
    tag = "v" + identity["version"]
    existing = find_release(github, tag, required_id=release_id, allow_empty_orphan=True)
    if (existing.get("target_commitish") != identity["source"]["commit"]
            or existing.get("body") != release_notes(identity)
            or existing.get("prerelease") is not False):
        raise ValueError("recovery release differs from original approved source")
    remote = release_assets(existing)
    proof = remote.get(PROVENANCE)
    if (not proof or proof.get("state") != "uploaded" or type(proof.get("size")) is not int
            or not 0 < proof["size"] <= 1024 * 1024):
        raise ValueError("recovery provenance is missing or unsafe")
    output.mkdir(parents=True)
    proof_path = output / PROVENANCE
    github.download(proof, proof_path)
    if release_update.sha(proof_path) != RECOVERY_PROVENANCE_SHA256:
        raise ValueError("recovery provenance differs from the pinned original SHA-256")
    verify_remote_asset(github, proof, proof_path)
    provenance = json.loads(proof_path.read_text(encoding="utf-8"))
    if (set(provenance) != {"schema", "repository", "version", "sequence", "source", "artifacts", "assets"}
            or provenance["schema"] != "rust-duty-game-release/v1"
            or any(provenance[key] != value for key, value in identity.items())):
        raise ValueError("pinned provenance does not match original build identity")
    artifacts = {}
    names = set()
    migrations = {}
    for platform, (target, executable, label, _) in build_identity.TARGETS.items():
        verified = build_identity.verify(Path(tested) / platform, platform, identity)
        artifacts[platform] = {"name": f"vector-range-{platform}-x64", "identity": verified}
        migration = "vector-range.exe" if platform == "windows" else "vector-range-linux-x64"
        migrations[migration] = Path(tested) / platform / executable
        names.update({f"Rust-Duty-{identity['version']}-{label}-x64.zip",
                      f"rust-duty-{identity['version']}-{target}.rdb", f"update-{target}.json", migration})
    if provenance["artifacts"] != artifacts or set(provenance["assets"]) != names:
        raise ValueError("pinned provenance artifact or release asset inventory differs")
    expected = {**provenance["assets"], PROVENANCE: release_update.asset(proof_path)}
    if set(remote) - set(expected) or not (set(expected) - set(remote)).issubset(migrations):
        raise ValueError("recovery may only add the two known missing migration executables")
    for name, asset in remote.items():
        if expected[name].get("name") != name:
            raise ValueError("provenance asset name mismatch")
        verify_remote_record(github, asset, expected[name])
    for name, source in migrations.items():
        destination = output / name
        shutil.copy2(source, destination)
        if release_update.asset(destination) != expected[name]:
            raise ValueError("original executable differs from pinned release provenance")
    # Re-read small manifests before promotion; archives/bundles retain the exact
    # server SHA-256 and sizes from the pinned, original verified provenance.
    for target, executable, _, _ in build_identity.TARGETS.values():
        name = f"update-{target}.json"
        local = output / name
        github.download(remote[name], local)
        verify_remote_asset(github, remote[name], local)
        manifest = release_update.verify_manifest(argparse.Namespace(
            manifest=local, assets_dir=None, version=identity["version"], target=target, bundle_only=True))
        if (manifest["sequence"] != identity["sequence"] or manifest["entrypoint"] != executable
                or manifest["bundle"] != expected.get(manifest["bundle"]["name"])):
            raise ValueError("original manifest does not bind the pinned complete game bundle")
    verify_tag(github, tag, identity["source"]["commit"])
    if existing.get("draft") is False:
        if set(remote) != set(expected):
            raise ValueError("published recovery release is incomplete; refusing mutation")
        verify_tag(github, tag, identity["source"]["commit"], required=True)
        return {"status": "already-published", "version": identity["version"], "url": existing["html_url"]}
    if existing.get("draft") is not True:
        raise ValueError("unknown recovery release state")
    if publication_order(identity, latest_identity(github)) != "newer":
        raise ValueError("recovery release may not replace an equal or newer channel")
    for name in sorted(set(expected) - set(remote)):
        github.upload(existing, output / name)
    complete = find_release(github, tag, required_id=release_id, allow_empty_orphan=True)
    final_assets = release_assets(complete)
    if set(final_assets) != set(expected):
        raise ValueError("recovered release assets remain incomplete")
    for name, asset in final_assets.items():
        verify_remote_record(github, asset, expected[name])
    if (complete.get("draft") is not True or complete.get("target_commitish") != identity["source"]["commit"]
            or complete.get("body") != release_notes(identity)
            or publication_order(identity, latest_identity(github)) != "newer"):
        raise ValueError("recovery target or channel changed before promotion")
    verify_tag(github, tag, identity["source"]["commit"])
    published = github.api(f"releases/{release_id}", payload={"draft": False, "make_latest": "true"})
    if published.get("id") != release_id or published.get("draft") is not False or published.get("tag_name") != tag:
        raise ValueError("recovered public release visibility was not confirmed")
    verify_tag(github, tag, identity["source"]["commit"], required=True)
    if publication_order(identity, latest_identity(github)) != "same":
        raise ValueError("recovered release is not latest discoverable update")
    return {"status": "published", "version": identity["version"], "url": published["html_url"]}



def verify_merged_authority(github, identity):
    """Independent read-only proof before any release or tag mutation."""
    if "merge" not in identity:
        return
    import merge_release_ledger as ledger
    _, state = ledger.read_state(github)
    pr = identity["merge"]["pull_request"]
    ledger.validate_record(state, pr, identity["source"]["commit"],
                           identity["version"], identity["sequence"], identity["source"]["run_id"])
    actual = github.api(f"pulls/{pr}")
    if (actual.get("number") != pr or actual.get("merged") is not True
            or actual.get("state") != "closed" or actual.get("draft") is not False
            or actual.get("base", {}).get("ref") != "main"
            or actual.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
            or actual.get("merge_commit_sha") != identity["source"]["commit"]):
        raise ValueError("publication allocation does not match an actual merged main PR")
    relation = github.api(f'compare/{identity["source"]["commit"]}...main?per_page=1')
    if relation.get("status") not in ("identical", "ahead"):
        raise ValueError("allocated source is no longer on main")
    run = github.api(f'actions/runs/{identity["source"]["run_id"]}')
    if (run.get("id") != identity["source"]["run_id"]
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("path") != identity["source"]["workflow"]
            or run.get("head_branch") != "main"
            or not (run.get("status") == "in_progress" or
                    (run.get("status") == "completed" and run.get("conclusion") == "success"))
            or run.get("event") not in ("pull_request_target", "workflow_dispatch", "schedule")):
        raise ValueError("canonical source run is not the trusted merged release workflow")
    latest_jobs = {}
    required_jobs = {"build / ubuntu-latest", "build / windows-latest"}
    for page in range(1, MAX_API_PAGES + 1):
        response = github.api(f'actions/runs/{identity["source"]["run_id"]}/jobs?filter=all&per_page=100&page={page}')
        jobs = response.get("jobs")
        if not isinstance(jobs, list) or len(jobs) > 100:
            raise ValueError("invalid canonical native build jobs response")
        for job in jobs:
            name = job.get("name")
            if name in required_jobs:
                if type(job.get("id")) is not int or job.get("run_id") != identity["source"]["run_id"]:
                    raise ValueError("native build job does not belong to the canonical run")
                if name not in latest_jobs or job["id"] > latest_jobs[name]["id"]:
                    latest_jobs[name] = job
        if len(jobs) < 100:
            break
    else:
        raise ValueError("canonical build jobs pagination limit reached")
    if (set(latest_jobs) != required_jobs or
            any(job.get("status") != "completed" or job.get("conclusion") != "success"
                for job in latest_jobs.values())):
        raise ValueError("both latest canonical native build jobs must have succeeded")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tested", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recover-release-id", type=int)
    parser.add_argument("--source-run-id", type=int)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    github = GitHub()
    if args.recover_release_id is not None:
        identity = recovery_identity(github, args.tested, args.recover_release_id,
                                     args.source_run_id, args.source_commit)
    else:
        if args.source_run_id is not None or args.source_commit is not None:
            parser.error("source run arguments require --recover-release-id")
        identity = build_identity.context(publication=True)
    if args.recover_release_id is not None:
        result = recover(github, args.tested, args.output, identity, args.recover_release_id)
    else:
        verify_merged_authority(github, identity)
        prepare(args.tested, args.output, identity)
        result = publish(github, args.output, identity)
    print(json.dumps(result, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f'Game update {result["version"]}: {result["status"]}.\n')
            if result.get("url"):
                stream.write(result["url"] + "\n")


if __name__ == "__main__":
    main()
