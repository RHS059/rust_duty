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
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

import build_identity
import package_game
import release_update

REPOSITORY = build_identity.REPOSITORY
PROVENANCE = "SOURCE_PROVENANCE.json"
DELIVERY_TARGETS = {"windows": build_identity.TARGETS["windows"]}


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


def prepare(tested, output, identity, previous_bundles=None):
    """Curate Windows through the strict game-build allowlist, with optional deltas."""
    tested, output = Path(tested), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("release preparation requires a fresh output directory")
    verified = {platform: build_identity.verify(tested / platform, platform, identity)
                for platform in DELIVERY_TARGETS}
    output.mkdir(parents=True)
    provenance = {"schema": "rust-duty-game-release/v1", **identity,
                  "artifacts": {}, "assets": {}}
    with tempfile.TemporaryDirectory(prefix=".game-release-", dir=output.parent) as directory:
        for platform, (target, executable, label, _) in DELIVERY_TARGETS.items():
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
            # Optional previous bundle. When present, release_update also emits a
            # delta from the one-file image of the executable already running, so a
            # content update does not download that binary again. Omitting it keeps
            # the one-time release manifest free of deltas.
            previous = (previous_bundles or {}).get(target)
            previous_path = previous_version = None
            if previous:
                previous_path, previous_version = previous
            release_update.prepare(argparse.Namespace(
                input=payload, output=output, version=identity["version"], sequence=identity["sequence"],
                target=target, entrypoint=executable, previous=previous_path,
                previous_version=previous_version))
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

    def upload(self, tag, path):
        # No --clobber: an uncertain upload is reconciled by a later rerun.
        subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", REPOSITORY], check=True)


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
        for target, executable, _, _ in DELIVERY_TARGETS.values():
            name = f"update-{target}.json"
            item = assets.get(name)
            if (not item or item.get("state") != "uploaded" or type(item.get("size")) is not int
                    or not 0 < item["size"] <= 1024 * 1024):
                raise ValueError("latest release lacks the complete Windows update manifest")
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
    first = manifests[0]
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
    return (f'Explicitly authorized one-time complete game build {identity["version"]}.\n\n'
            f'Source: {identity["source"]["commit"]}\n'
            f'Branch: {identity["source"]["branch"]}\n'
            f'Build: {identity["source"]["run_url"]}\n'
            f'Update sequence: {identity["sequence"]}\n\n'
            'Windows checks and authored-asset validation passed before publication. '
            'Linux-hosted native validation is a separate evidence lane. Full managed updates and complete '
            'game ZIPs contain only the approved packaging allowlist. User settings and '
            'private soldier assets are excluded from managed updates.\n\n'
            'Trust: RHS059/rust_duty over GitHub HTTPS, with payload sizes and SHA-256. '
            'There is no independent signing key. See SOURCE_PROVENANCE.json for exact '
            'build identities and asset hashes.')


def verify_remote_asset(github, remote, local):
    expected = release_update.asset(local)
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


def publish(github, output, identity):
    output = Path(output)
    tag = "v" + identity["version"]
    notes = release_notes(identity)
    expected = {path.name: path for path in output.iterdir() if path.is_file()}
    required = {PROVENANCE, "vector-range.exe", f'Rust-Duty-{identity["version"]}-Windows-x64.zip'}
    target = DELIVERY_TARGETS['windows'][0]
    manifest_name = f'update-{target}.json'
    if manifest_name not in expected:
        raise ValueError("incomplete one-time release asset set")
    manifest = release_update.verify_manifest(argparse.Namespace(
        manifest=expected[manifest_name], assets_dir=output,
        version=identity['version'], target=target, bundle_only=False))
    required.update((manifest_name, manifest['bundle']['name']))
    required.update(delta['asset']['name'] for delta in manifest['deltas'])
    if set(expected) != required:
        raise ValueError("incomplete or unexpected one-time release asset set")
    latest = latest_identity(github)
    order = publication_order(identity, latest)
    if order == "superseded":
        return {"status": "superseded", "version": identity["version"], "latest": latest}
    existing = github.api(f"releases/tags/{tag}", missing_ok=True)
    verify_tag(github, tag, identity["source"]["commit"])
    if existing is None:
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
    if existing.get("draft") is False:
        if set(remote) != set(expected):
            raise ValueError("published release is incomplete; refusing mutation")
        verify_tag(github, tag, identity["source"]["commit"], required=True)
        return {"status": "already-published", "version": identity["version"], "url": existing["html_url"]}
    if existing.get("draft") is not True:
        raise ValueError("unknown release state")
    for name in sorted(set(expected) - set(remote)):
        github.upload(tag, expected[name])
    complete = github.api(f'releases/{existing["id"]}')
    remote = release_assets(complete)
    if set(remote) != set(expected):
        raise ValueError("uploaded release asset set is incomplete")
    for name, asset in remote.items():
        verify_remote_asset(github, asset, expected[name])
    # Check once again immediately before the atomic visibility/latest change.
    order = publication_order(identity, latest_identity(github))
    if order != "newer":
        if order == "superseded":
            return {"status": "superseded-draft", "version": identity["version"]}
        raise ValueError("channel changed during draft publication")
    verify_tag(github, tag, identity["source"]["commit"])
    published = github.api(f'releases/{existing["id"]}', payload={"draft": False, "make_latest": "true"})
    if published.get("draft") is not False or published.get("tag_name") != tag:
        raise ValueError("public release visibility was not confirmed")
    verify_tag(github, tag, identity["source"]["commit"], required=True)
    if publication_order(identity, latest_identity(github)) != "same":
        raise ValueError("published release is not the latest discoverable game update")
    return {"status": "published", "version": identity["version"], "url": published["html_url"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tested", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = build_identity.context(publication=True)
    prepare(args.tested, args.output, identity)
    result = publish(GitHub(), args.output, identity)
    print(json.dumps(result, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f'One-time update {result["version"]}: {result["status"]}.\n')
            if result.get("url"):
                stream.write(result["url"] + "\n")


if __name__ == "__main__":
    main()
