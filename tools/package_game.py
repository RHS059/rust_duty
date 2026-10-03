#!/usr/bin/env python3
"""Verify and stage the complete game with the frozen locomotion companions.

Only the explicitly named distribution files are copied. User settings are
included in fresh build artifacts, never in managed update payloads.
"""
from __future__ import annotations
import argparse
import gzip
import io
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import zlib
import vrview
from build_blender_assets import selections
from merge_walk_clip import clip_offset

WALK_DIR = Path("assets/walk")
WALK_META = ("manifest.json", "parity.json", "conversion.json")

GENERATED_DIR = Path("assets/reload")
GENERATED_FILES = (*("asset." + suffix for suffix in ("vra", "vrs", "vrm")),
                   "manifest.json", "export-manifest.json", "source.json", "parity.json")

ASSET_DIR = Path("assets/locomotion")
COMPANIONS = ("asset.vra", "asset.vrs", "asset.vrm")
CLIPS = (
    "normal_ready", "normal_entry", "normal_loop", "normal_exit",
    "normal_entry_connected", "normal_loop_to_exit", "normal_exit_connected",
    *(f"normal_exit_bridge_{i:03d}" for i in range(35)), "normal_settle",
)
NOTICES = ("LICENSE", "THIRD_PARTY_LICENSES.txt",
           "updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt")
BUILD_FILES = (
    "settings.cfg", "README.md", "docs/PROVENANCE.md", "docs/ASSET_FORMAT.md",
    "docs/M4_PROFILE.md", "docs/FIRST_PERSON_ARMS.md", "docs/MANTLING.md",
    "docs/AUTHORED_LOCOMOTION_REVISION.md", "docs/AUTHORED_ASSET_CI.md", "assets/README.md",
    "profiles/kestrel.cfg", "profiles/m4a1-beta-visual.cfg", "profiles/m4a1-candidate.cfg",
)


def regular_file(root: Path, relative: str | Path) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe distribution path: {relative}")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"symlink in distribution path: {relative}")
    if not current.is_file():
        raise ValueError(f"required distribution file missing: {relative}")
    return current



def companion_bytes(root: Path, name: str, manifest: dict, asset_dir: Path = ASSET_DIR) -> bytes:
    record = manifest["files"][name]
    if (set(record) != {"bytes", "sha256"}
            or type(record["bytes"]) is not int
            or not 0 < record["bytes"] <= 128 * 1024**2):
        raise ValueError(f"invalid companion manifest: {name}")
    raw = root / asset_dir / name
    if raw.exists() or raw.is_symlink():
        path = regular_file(root, asset_dir / name)
        if path.stat().st_size != record["bytes"]:
            raise ValueError(f"locomotion size mismatch: {name}")
        blob = path.read_bytes()
    elif name in manifest.get("repository_transport", {}):
        transport = manifest["repository_transport"][name]
        path = regular_file(root, asset_dir / transport["file"])
        if path.stat().st_size != transport["bytes"]:
            raise ValueError("compressed locomotion size mismatch")
        packed = path.read_bytes()
        if hashlib.sha256(packed).hexdigest() != transport["sha256"]:
            raise ValueError("compressed locomotion SHA-256 mismatch")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
                blob = stream.read(record["bytes"] + 1)
        except (OSError, EOFError) as error:
            raise ValueError("invalid compressed locomotion asset") from error
        if len(blob) != record["bytes"]:
            raise ValueError("decompressed locomotion size mismatch")
    else:
        raise ValueError(f"required distribution file missing: {asset_dir / name}")
    if hashlib.sha256(blob).hexdigest() != record["sha256"]:
        raise ValueError(f"locomotion SHA-256 mismatch: {name}")
    return blob


def verify(root: Path) -> dict:
    root = Path(root)
    manifest = json.loads(regular_file(root, ASSET_DIR / "manifest.json").read_text())
    if (manifest.get("schema") != "rust-duty-locomotion-distribution/v1"
            or manifest.get("clip_names") != list(CLIPS)
            or manifest.get("clip_count") != 43
            or set(manifest.get("files", {})) != set(COMPANIONS)):
        raise ValueError("invalid locomotion distribution manifest")
    transports = manifest.get("repository_transport", {})
    if set(transports) != {"asset.vrs"}:
        raise ValueError("invalid locomotion transport manifest")
    transport = transports["asset.vrs"]
    if (set(transport) != {"file", "encoding", "bytes", "sha256", "decoded_bytes", "decoded_sha256"}
            or transport["file"] != "asset.vrs.gz" or transport["encoding"] != "gzip"
            or type(transport["bytes"]) is not int or not 0 < transport["bytes"] <= 128 * 1024**2
            or transport["decoded_bytes"] != manifest["files"]["asset.vrs"]["bytes"]
            or transport["decoded_sha256"] != manifest["files"]["asset.vrs"]["sha256"]):
        raise ValueError("invalid locomotion transport manifest")
    blobs = {name: companion_bytes(root, name, manifest) for name in COMPANIONS}
    data = blobs["asset.vra"]
    if len(data) < 24:
        raise ValueError("truncated locomotion VRA")
    magic, version, length, checksum, flags = struct.unpack_from("<8sIIII", data)
    payload = data[24:]
    if (magic != b"VRANIM01" or version != 1 or flags != 0
            or length != len(payload) or zlib.crc32(payload) != checksum):
        raise ValueError("invalid locomotion VRA header or payload CRC")
    offset = 0

    def take(size):
        nonlocal offset
        if size < 0 or offset + size > len(payload):
            raise ValueError("truncated locomotion VRA record")
        result = payload[offset:offset + size]
        offset += size
        return result

    def u32():
        return struct.unpack("<I", take(4))[0]

    def name():
        return take(struct.unpack("<H", take(2))[0]).decode("utf-8")

    if (u32() != zlib.crc32(blobs["asset.vrs"])
            or u32() != zlib.crc32(blobs["asset.vrm"])):
        raise ValueError("locomotion companion binding CRC mismatch")
    bones = u32()
    if bones != 72:
        raise ValueError("unexpected locomotion bone count")
    for _ in range(bones):
        name()
        take(4)
    actors = u32()
    if actors != 2:
        raise ValueError("unexpected locomotion actor count")
    for _ in range(actors):
        name()
        take(u32() * 4 + 64)
    if u32() != len(CLIPS):
        raise ValueError("unexpected locomotion clip count")
    for expected in CLIPS:
        if name() != expected or u32() not in (0, 1):
            raise ValueError(f"unexpected locomotion clip record: {expected}")
        frames = u32()
        if not 1 <= frames <= 10000:
            raise ValueError("invalid locomotion frame count")
        take(frames * (4 + (bones + actors) * 40 + actors))
    if offset != len(payload):
        raise ValueError("trailing locomotion VRA data")
    regular_file(root, ASSET_DIR / "README.md")
    return {"clip_count": len(CLIPS), "files": manifest["files"]}


def walk_bound(root: Path) -> bool:
    path = root / "assets/animations.cfg"
    if not path.exists():
        return False
    lines = [line.strip() for line in path.read_text().splitlines()]
    bindings = [line.split("=", 1)[1].strip() for line in lines if line.startswith("regular_walk.asset=")]
    if bindings and bindings != ["walk/asset.vra"]:
        raise ValueError("unsupported packaged walk asset binding")
    return bool(bindings)


def verify_walk(root: Path, folder: Path = WALK_DIR) -> dict:
    root = Path(root)
    manifest = json.loads(regular_file(root, folder / "manifest.json").read_text())
    source = manifest.get("source", {})
    if (manifest.get("schema") != "rust-duty-authored-walk-distribution/v1"
            or manifest.get("clip_count") != 44
            or manifest.get("clip_names") != [*CLIPS, "normal_walk_r1"]
            or manifest.get("walk_clip") != "normal_walk_r1" or manifest.get("loop") is not True
            or set(manifest.get("files", {})) != set(COMPANIONS)
            or source.get("file") != "assets/authoring/locomotion/locomotion.blend"
            or source.get("action") != "normal_walk_r1" or source.get("fps") != 60
            or source.get("frame_start") != 1 or source.get("frame_end") != 45):
        raise ValueError("invalid authored walk manifest")
    transports = manifest.get("repository_transport", {})
    transport = transports.get("asset.vrs", {})
    if (set(transports) != {"asset.vrs"} or transport.get("file") != "asset.vrs.gz"
            or transport.get("encoding") != "gzip" or type(transport.get("bytes")) is not int
            or not 0 < transport["bytes"] <= 128 * 1024**2
            or transport.get("decoded_bytes") != manifest["files"]["asset.vrs"]["bytes"]
            or transport.get("decoded_sha256") != manifest["files"]["asset.vrs"]["sha256"]):
        raise ValueError("invalid walk transport manifest")
    blobs = {name: companion_bytes(root, name, manifest, folder) for name in COMPANIONS}
    baseline = json.loads(regular_file(root, ASSET_DIR / "manifest.json").read_text())
    old = companion_bytes(root, "asset.vra", baseline)
    new = blobs["asset.vra"]
    old_offset, new_offset = clip_offset(old), clip_offset(new)
    if (new[24:new_offset] != old[24:old_offset]
            or new[new_offset + 4:new_offset + len(old) - old_offset] != old[old_offset + 4:]):
        raise ValueError("walk changed original locomotion clip bytes or bindings")
    for name in ("asset.vrs", "asset.vrm"):
        if manifest["files"][name] != baseline["files"][name]:
            raise ValueError("walk changed canonical companions")
    pack = vrview.decode_vra(new, vrs=blobs["asset.vrs"], vrm=blobs["asset.vrm"])
    if ([clip["name"] for clip in pack["clips"]] != [*CLIPS, "normal_walk_r1"]
            or not pack["clips"][-1]["loop"]
            or pack["clips"][-1]["frames"][-1]["time"] != struct.unpack("<f", struct.pack("<f", 44 / 60))[0]):
        raise ValueError("walk loop clip contract mismatch")
    parity = json.loads(regular_file(root, folder / "parity.json").read_text())
    conversion = json.loads(regular_file(root, folder / "conversion.json").read_text())
    if (parity.get("backend") != "Rust CPU sampler" or parity.get("passed") is not True
            or parity.get("asset_sha256") != manifest["files"]["asset.vra"]["sha256"]
            or parity.get("source_sha256", {}).get("locomotion.blend") != source.get("sha256")
            or parity.get("source_fbx_sha256") != source.get("fbx", {}).get("sha256")
            or parity.get("clip") != "normal_walk_r1" or parity.get("samples", 0) < 25
            or parity.get("visibility_failures") != 0
            or conversion.get("authoring_master_sha256") != source.get("sha256")
            or conversion.get("source_fbx_sha256") != source["fbx"]["sha256"]
            or conversion.get("native_fps") != [60, 1]
            or conversion.get("source_take") != "normal_walk_r1"):
        raise ValueError("walk lacks matching successful source/Rust parity")
    current_source = root / source["file"]
    if current_source.exists():
        data = regular_file(root, source["file"]).read_bytes()
        if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("walk differs from committed Blender source")
    return {"clip": "normal_walk_r1", "clip_count": 44, "original_clips_preserved": 43,
            "source_sha256": source["sha256"], "parity_samples": parity["samples"]}


ADS_DIR = Path('assets/ads')
ADS_CLIPS = ('ads_entry_r1', 'ads_hold_r1', 'ads_exit_r1')
ADS_META = ('manifest.json', *(f'{kind}-{clip}.json' for clip in ADS_CLIPS for kind in ('parity', 'conversion')))


def ads_bound(root: Path) -> bool:
    path = root / 'assets/animations.cfg'
    if not path.exists():
        return False
    lines = [line.strip() for line in path.read_text().splitlines()]
    bindings = [line.split('=', 1)[1].strip() for line in lines if line.startswith('ads.asset=')]
    if bindings and bindings != ['ads/asset.vra']:
        raise ValueError('unsupported packaged ADS asset binding')
    return bool(bindings)


def verify_ads(root: Path, folder: Path = ADS_DIR) -> dict:
    root = Path(root)
    manifest = json.loads(regular_file(root, folder / 'manifest.json').read_text())
    source = manifest.get('source', {})
    names = [*CLIPS, 'normal_walk_r1', *ADS_CLIPS]
    ads = manifest.get('ads_clips', [])
    if (manifest.get('schema') != 'rust-duty-authored-ads-distribution/v1'
            or manifest.get('clip_count') != 47 or manifest.get('clip_names') != names
            or set(manifest.get('files', {})) != set(COMPANIONS)
            or source.get('file') != 'assets/authoring/ads/ads.blend'
            or source.get('fps') != 60 or source.get('bake_hz') != 480
            or [c.get('name') for c in ads] != list(ADS_CLIPS)
            or [c.get('loop') for c in ads] != [False, True, False]
            or [c.get('duration') for c in ads] != [.25, 1., .25]
            or any(c.get('frame_start') != 1 for c in ads)
            or [c.get('frame_end') for c in ads] != [16, 61, 16]):
        raise ValueError('invalid authored ADS manifest')
    transports = manifest.get('repository_transport', {})
    if set(transports) != {'asset.vra', 'asset.vrs'}:
        raise ValueError('invalid ADS transport manifest')
    for name, transport in transports.items():
        if (transport.get('file') != name + '.gz' or transport.get('encoding') != 'gzip'
                or type(transport.get('bytes')) is not int or not 0 < transport['bytes'] <= 128 * 1024**2
                or transport.get('decoded_bytes') != manifest['files'][name]['bytes']
                or transport.get('decoded_sha256') != manifest['files'][name]['sha256']):
            raise ValueError('invalid ADS transport manifest')
    blobs = {name: companion_bytes(root, name, manifest, folder) for name in COMPANIONS}
    walk = json.loads(regular_file(root, WALK_DIR / 'manifest.json').read_text())
    old = companion_bytes(root, 'asset.vra', walk, WALK_DIR); new = blobs['asset.vra']
    old_offset, new_offset = clip_offset(old), clip_offset(new)
    if (new[24:new_offset] != old[24:old_offset]
            or new[new_offset + 4:new_offset + len(old) - old_offset] != old[old_offset + 4:]):
        raise ValueError('ADS changed original walk44 clip bytes or bindings')
    for name in ('asset.vrs', 'asset.vrm'):
        if manifest['files'][name] != walk['files'][name]:
            raise ValueError('ADS changed canonical companions')
    pack = vrview.decode_vra(new, vrs=blobs['asset.vrs'], vrm=blobs['asset.vrm'])
    if ([c['name'] for c in pack['clips']] != names
            or [c['loop'] for c in pack['clips'][-3:]] != [False, True, False]
            or [c['frames'][-1]['time'] for c in pack['clips'][-3:]] != [.25, 1., .25]):
        raise ValueError('ADS clip contract mismatch')
    samples = 0
    for clip in ADS_CLIPS:
        parity = json.loads(regular_file(root, folder / f'parity-{clip}.json').read_text())
        conversion = json.loads(regular_file(root, folder / f'conversion-{clip}.json').read_text())
        if (parity.get('backend') != 'Rust CPU sampler' or parity.get('passed') is not True
                or parity.get('asset_sha256') != manifest['files']['asset.vra']['sha256']
                or parity.get('source_sha256', {}).get('ads.blend') != source.get('sha256')
                or parity.get('source_fbx_sha256') != source.get('fbx', {}).get('sha256')
                or parity.get('clip') != clip or parity.get('samples', 0) < 25
                or parity.get('visibility_failures') != 0
                or conversion.get('authoring_master_sha256') != source.get('sha256')
                or conversion.get('source_fbx_sha256') != source.get('fbx', {}).get('sha256')
                or conversion.get('native_fps') != [60, 1] or conversion.get('source_take') != clip):
            raise ValueError('ADS lacks matching successful source/Rust parity')
        samples += parity['samples']
    current_source = root / source['file']
    if current_source.exists():
        data = regular_file(root, source['file']).read_bytes()
        if len(data) != source['bytes'] or hashlib.sha256(data).hexdigest() != source['sha256']:
            raise ValueError('ADS differs from committed Blender source')
    return {'clips': list(ADS_CLIPS), 'clip_count': 47, 'original_clips_preserved': 44,
            'source_sha256': source['sha256'], 'parity_samples': samples}


def materialize(root: Path, include_walk: bool = False, include_ads: bool = False) -> dict:
    """Decode verified repository transport for native tests/tools in this checkout."""
    root = Path(root)
    report = verify(root)
    manifest = json.loads(regular_file(root, ASSET_DIR / "manifest.json").read_text())
    for name in COMPANIONS:
        destination = root / ASSET_DIR / name
        if not destination.exists():
            blob = companion_bytes(root, name, manifest)
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".materialize-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(blob)
            try:
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
    verify(root)
    if include_walk and walk_bound(root):
        report["walk"] = verify_walk(root)
        walk_manifest = json.loads(regular_file(root, WALK_DIR / "manifest.json").read_text())
        for name in COMPANIONS:
            target = root / WALK_DIR / name
            if not target.exists():
                target.write_bytes(companion_bytes(root, name, walk_manifest, WALK_DIR))
        verify_walk(root)
    if include_ads and ads_bound(root):
        report['ads'] = verify_ads(root)
        ads_manifest = json.loads(regular_file(root, ADS_DIR / 'manifest.json').read_text())
        for name in COMPANIONS:
            target = root / ADS_DIR / name
            if not target.exists():
                target.write_bytes(companion_bytes(root, name, ads_manifest, ADS_DIR))
        verify_ads(root)
    return report


def verify_generated_pack(root: Path, folder: Path, expected_source=None) -> dict:
    """Bind shipped companions, successful Rust parity and canonical source hashes."""
    root = Path(root)
    blobs = {name: regular_file(root, folder / name).read_bytes()
             for name in GENERATED_FILES}
    manifest = json.loads(blobs["manifest.json"])
    exported = json.loads(blobs["export-manifest.json"])
    source = json.loads(blobs["source.json"])
    parity = json.loads(blobs["parity.json"])
    if (source.get("schema") != "rust-duty-blender-source/v1"
            or set(manifest.get("files", {})) != set(COMPANIONS)
            or manifest.get("authoring_master_sha256") != source.get("sha256")
            or exported.get("source_sha256") != source.get("sha256")
            or exported.get("action") != source.get("action")
            or exported.get("native_requested_range") != source.get("native_range")
            or manifest.get("native_crop") != source.get("native_range")
            or not exported.get("action_inventory")
            or manifest.get("source_fbx_sha256") != exported.get("files", {}).get("current-full-wip.fbx", {}).get("sha256")):
        raise ValueError("generated source/export manifest mismatch")
    for name in COMPANIONS:
        if manifest["files"][name] != {"bytes": len(blobs[name]), "sha256": hashlib.sha256(blobs[name]).hexdigest()}:
            raise ValueError(f"generated companion hash mismatch: {name}")
    if (parity.get("passed") is not True or parity.get("backend") != "Rust CPU sampler"
            or parity.get("asset_sha256") != manifest["files"]["asset.vra"]["sha256"]
            or parity.get("source_witnesses_sha256") != exported["files"].get("source-witnesses.npz", {}).get("sha256")
            or parity.get("visibility_failures") != 0 or parity.get("samples", 0) < 1):
        raise ValueError("generated assets lack matching passed Rust parity")
    if expected_source is not None and source != expected_source:
        raise ValueError("alternate source selection mismatch")
    committed = root / "assets/source/reload/source.json"
    if folder == GENERATED_DIR and committed.exists() and json.loads(committed.read_text()) != source:
        raise ValueError("generated assets differ from current committed source")
    pack = vrview.decode_vra(blobs["asset.vra"], vrs=blobs["asset.vrs"], vrm=blobs["asset.vrm"])
    if [clip["name"] for clip in pack["clips"]] != [source.get("clip")]:
        raise ValueError("generated clip differs from selected source")
    regular_file(root, "assets/animations.cfg")
    regular_file(root, "docs/ANIMATION_SLOTS.md")
    return {"clip": source["clip"], "source_sha256": source["sha256"], "parity_samples": parity["samples"]}


def generated_paths(root):
    source = json.loads(regular_file(root, GENERATED_DIR / "source.json").read_text())
    for key, selected in selections(source):
        folder = GENERATED_DIR / "alternates" / key if key else GENERATED_DIR
        yield folder, selected


def verify_generated(root: Path) -> dict:
    reports = {}
    for folder, selected in generated_paths(root):
        reports[str(folder)] = verify_generated_pack(root, folder, selected)
    primary = reports[str(GENERATED_DIR)]
    primary["selected_packs"] = len(reports)
    if walk_bound(root):
        primary["walk"] = verify_walk(root)
    if ads_bound(root):
        primary["ads"] = verify_ads(root)
    return primary


def stage(root: Path, binary: str, output: Path, update: bool = False, require_generated: bool = False) -> dict:
    root, output = Path(root).resolve(), Path(output).absolute()
    if Path(binary).name not in ("vector-range", "vector-range.exe"):
        raise ValueError("unexpected game executable name")
    if output.exists() or output.is_symlink():
        raise ValueError("refusing to replace an existing distribution")
    if output == root or output in root.parents:
        raise ValueError("output must not contain source")
    report = verify(root)
    generated = require_generated or (root / "assets/animations.cfg").exists()
    if generated:
        report["generated_reload"] = verify_generated(root)
    walking = walk_bound(root)
    if walking:
        report["walk"] = verify_walk(root)
    aiming = ads_bound(root)
    if aiming:
        report['ads'] = verify_ads(root)
    copies = [(regular_file(root, binary), Path(binary).name)]
    if aiming:
        for name in (*ADS_META, 'README.md'):
            copies.append((regular_file(root, ADS_DIR / name), ADS_DIR / name))
    if walking:
        for name in WALK_META:
            copies.append((regular_file(root, WALK_DIR / name), WALK_DIR / name))
        copies.append((regular_file(root, WALK_DIR / "README.md"), WALK_DIR / "README.md"))
    if generated:
        for relative in [*(folder / name for folder, _ in generated_paths(root) for name in GENERATED_FILES),
                         Path("assets/animations.cfg"), Path("docs/ANIMATION_SLOTS.md")]:
            copies.append((regular_file(root, relative), relative))
    for relative in NOTICES:
        # Keep updater notices at the artifact path expected by subsequent staging.
        copies.append((regular_file(root, relative), relative))
    for relative in ("manifest.json", "README.md"):
        relative = ASSET_DIR / relative
        copies.append((regular_file(root, relative), relative))
    if not update:
        for relative in BUILD_FILES:
            copies.append((regular_file(root, relative), relative))
        # Retain the independently approved legacy weapon when it is supplied.
        legacy = Path("assets/weapons/hk416a5.vrm")
        if (root / legacy).exists() or (root / legacy).is_symlink():
            copies.append((regular_file(root, legacy), legacy))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-game-", dir=output.parent) as temporary:
        destination = Path(temporary) / "game"
        destination.mkdir()
        for source, relative in copies:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        manifest = json.loads((root / ASSET_DIR / "manifest.json").read_text())
        for name in COMPANIONS:
            (destination / ASSET_DIR / name).write_bytes(companion_bytes(root, name, manifest))
        if walking:
            walk_manifest = json.loads(regular_file(root, WALK_DIR / "manifest.json").read_text())
            for name in COMPANIONS:
                (destination / WALK_DIR / name).write_bytes(companion_bytes(root, name, walk_manifest, WALK_DIR))
            verify_walk(destination)
        if aiming:
            ads_manifest = json.loads(regular_file(root, ADS_DIR / 'manifest.json').read_text())
            for name in COMPANIONS:
                target = destination / ADS_DIR / name
                target.write_bytes(companion_bytes(root, name, ads_manifest, ADS_DIR))
            verify_ads(destination)
        verify(destination)
        if generated:
            verify_generated(destination)
        destination.rename(output)
    return {"output": str(output), "files_staged": len(copies) + len(COMPANIONS) + (len(COMPANIONS) if walking else 0) + (len(COMPANIONS) if aiming else 0), **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--root", type=Path, default=Path("."))
    check.add_argument("--require-generated", action="store_true")
    unpack = commands.add_parser("materialize")
    unpack.add_argument("--root", type=Path, default=Path("."))
    unpack.add_argument("--include-walk", action="store_true")
    unpack.add_argument("--include-ads", action="store_true")
    walk = commands.add_parser("verify-walk")
    walk.add_argument("--root", type=Path, default=Path("."))
    walk.add_argument("--folder", type=Path, default=WALK_DIR)
    packaging = commands.add_parser("stage")
    packaging.add_argument("--root", type=Path, default=Path("."))
    packaging.add_argument("--binary", required=True)
    packaging.add_argument("--output", type=Path, required=True)
    packaging.add_argument("--update", action="store_true")
    packaging.add_argument("--require-generated", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        report = verify(args.root)
    elif args.command == "materialize":
        report = materialize(args.root, args.include_walk, args.include_ads)
    elif args.command == "verify-walk":
        report = verify_walk(args.root, args.folder)
    else:
        report = stage(args.root, args.binary, args.output, args.update, args.require_generated)
    if args.command == "verify" and args.require_generated:
        report["generated_reload"] = verify_generated(args.root)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
