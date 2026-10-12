#!/usr/bin/env python3
"""Prepare a FRESH public-source Linux game package on a CPU-only Linux host.

This script never runs a graphics/window command, allocates a GPU, renders, reads
credentials, publishes, or reuses an older executable/identity receipt.
Asset mode is explicit: public-release revalidates a pinned public asset-only
overlay; regenerate builds authored inputs anew. Neither uses the release binary.
The pinned source is production commit49; support-commit identifies only these
preparation tools. No source/worktree argument exists: every run creates its own
new disposable Git checkout below --runs-root. --dry-run performs no writes or
network operations. Full cold-build duration is deliberately not predicted.
"""
from __future__ import annotations

import argparse
import ctypes.util
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
import stat
import tomllib
import urllib.request
import urllib.parse

SOURCE_COMMIT = "49c3bf9b3d0482ce81a7d50683904bda28468d7d"
JUMP_COMMIT = "e9317f90ea171976306e2f17c111325d948ea357"
JUMP_SHA = "a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b"
RELEASE_URL = "https://github.com/RHS059/rust_duty/releases/download/v0.1.9/Rust-Duty-0.1.9-Linux-x64.zip"
RELEASE_SHA = "b4978796abf0b3301649ae885bf5cce1c0043036ee5297cfc6220ec933b3a5d0"
RELEASE_BYTES = 102577561
ASSET_GROUPS = ("locomotion", "walk", "ads", "directional", "jump", "reload")
MATRIX_COMMIT = "b73588d13fcf3329f1485f9bf1187dee55b7ed55"
MATRIX_FILES = {
    "performance_matrix.py": "0ed631bddcfa0290ce260daf38c4822720bd1392e5f1a94d6b54df77231495dd",
    "performance_matrix_driver.py": "8a8987a39477dd0f126301d6303ffeefbb1c5bfd20c8bf1afef9b17fcd56b06f",
    "summarize_frame_performance.py": "e88a3e94a031c3687ada16962f4d49649d71b1ed9861088fbb03422fb7bd3fbe",
    "exclusive_output.py": "a8f5ed95a0f9e4f085a865e0dcdc8d7ce0d323226e4e9de76893aca6d1c6fce3",
}
HARNESS_SHA = "23d86f65054fb1fee335d0b5e2b72615e4cf862e4de836acba249361ee210b78"
PATCH_SHA = "1b72e875031273094e756dfa0c1a914dbecb8d8200f3d5547ceed30243144136"
CRATE_SHA = "b6b7fb58561a792bc237628ba0792e332de418fefe145f13b5ed8201e6d52f58"
EGL_BEFORE = "25ef4629921f6b87daa559f62f3a6132f766451e4e3674cdec62e9d8ecac2627"
EGL_AFTER = "fcd94fc2185dbb21bf3e6e82f8a77e81d3025a76344f337250f026194b4741c8"
BLENDER_URL = "https://download.blender.org/release/Blender4.3/blender-4.3.2-linux-x64.tar.xz"
BLENDER_SHA = "4da1c956673c0485e63054e563ee69198cc8f80d8157dd7592dffc8a6a5592e6"
RUST_BASE = "https://static.rust-lang.org/dist/2026-10-01/"
RUST_COMPONENTS = {
    "rustc": "77171ba2a0345fdf2abc4fedda55d6de078dae7a68527c28be8c77dcc9604bd5",
    "rust-std": "3e58dff2d0b72196b5ea4e90536e174d400de88564a52694686b81e091169933",
    "cargo": "d7674918d28093097614cd9728b6ca60db9ea3038f640f0bd1e9a4188c7568ce",
    "rustfmt": "b22c09ab9e258ec5571da170d88bd1624a4ea602e6d70d95720c5b47494cadce",
    "clippy": "982442e32ad8dd3f0bb3a30db74038da5f71fd9bf1a865cc71da8ea5d4ec71ec",
}
AUTHORING_PINS = {
    "assets/source/reload/current.blend": "8cec36c6bfcc4967cb80629b40ecdced3c0b5507914aec7eb3d2d614f2d758fd",
    "assets/authoring/locomotion/locomotion.blend": "1b01f49d7fe92f39c7bd180823ee4556a0074dd9ff8ef9c10b3fb4d3f3059e43",
    "assets/authoring/ads/ads.blend": "3acdf3e2d04757d719ba59ede08decdf8bad48e2e87d9448046fe8edcbba4f58",
    "assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend": "36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d",
}
SPARSE_PATHS = (
    "Cargo.toml", "Cargo.lock", "build.rs", "build_number.rs", "settings.cfg",
    "README.md", "LICENSE", "THIRD_PARTY_LICENSES.txt", "src/", "tools/", "updater/",
    "docs/", "profiles/", "ui/", "examples/sample_viewmodel_clip.rs",
    ".github/actions/setup-blender/action.yml", "assets/README.md", "assets/animations.cfg",
    "assets/locomotion/", "assets/walk/README.md", "assets/ads/README.md", "assets/jump/README.md",
    "assets/weapons/hk416a5.vrm", "assets/source/reload/current.blend", "assets/source/reload/source.json",
    "assets/authoring/locomotion/locomotion.blend", "assets/authoring/locomotion/export_config.json",
    "assets/authoring/locomotion/export_locomotion.py", "assets/authoring/locomotion/source_integrity.py",
    "assets/authoring/locomotion/source_integrity.json",
    "assets/authoring/ads/ads.blend", "assets/authoring/ads/export_config.json",
    "assets/authoring/ads/source_integrity.py", "assets/authoring/ads/source_integrity.json",
    "assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend",
    "assets/authoring/locomotion_directional/runtime_export_config.json",
    "assets/authoring/locomotion_directional/export_directional_preview.py",
    "assets/authoring/locomotion_directional/r5/source_integrity.json",
    "assets/authoring/jump/export_config.json",
)
APT_PACKAGES = ("git", "build-essential", "pkg-config", "patch", "xz-utils", "python3-venv",
                "libx11-6", "libxi6", "libxfixes3", "libxrender1", "libxkbcommon0", "libgl1", "libegl1")
GIT = ["git", "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null", "-c", "core.askPass=",
       "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never"]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Expected regular file: " + str(path))
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def pin(value, length=64):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{%d}" % length, value), "Missing or invalid immutable pin")
    return value


def sanitized_env(root):
    """Allowlist, never inspect credentials or inherit HOME/config/token variables."""
    root = Path(root)
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "XDG_CONFIG_HOME": str(root / "config"), "NETRC": str(root / "empty-netrc"),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(root / "tmp"),
        "TMP": str(root / "tmp"), "TEMP": str(root / "tmp"),
        "CARGO_HOME": str(root / "cargo"), "CARGO_TARGET_DIR": str(root / "target"),
        "RUSTUP_HOME": str(root / "rustup-unused"), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
        "GCM_INTERACTIVE": "never", "GIT_LFS_SKIP_SMUDGE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1", "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void", "CI": "true",
        "CARGO_NET_RETRY": "2", "CARGO_HTTP_TIMEOUT": "60", "CARGO_HTTP_LOW_SPEED_LIMIT": "1000",
    }
    # Preserve the caller's HOME value; no task-specific HOME override. Credentials
    # are excluded by the env allowlist and explicit Git/pip/Cargo config controls.
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    return env


def anonymous_git_preflight():
    """Old Git/libcurl may ignore NETRC env; reject default netrc without reading it."""
    default = Path.home() / ".netrc"
    require(not default.exists() and not default.is_symlink(),
            "Anonymous Git fetch blocked: default .netrc exists; use a credential-free CPU host")


def gpu_gate(run=subprocess.run, which=shutil.which, dev_root=Path("/dev")):
    """Query before any setup; unknown inventory fails closed. Absence is recorded."""
    devices = [p.name for p in dev_root.glob("nvidia[0-9]*")]
    command = which("nvidia-smi", path="/usr/local/bin:/usr/bin:/bin")
    if command is None:
        require(not devices, "NVIDIA device nodes exist but inventory is unavailable")
        return {"status": "empty", "nvidia_smi": "absent", "device_nodes": []}
    result = run([command, "--query-gpu=index,name,uuid", "--format=csv,noheader"],
                 capture_output=True, text=True, timeout=20,
                 env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C"})
    output = result.stdout.strip()
    no_devices = (result.stdout + result.stderr).strip() == "No devices were found"
    if result.returncode != 0:
        require(no_devices and not devices,
                "NVIDIA inventory could not be verified empty")
    else:
        require((not output or no_devices) and not devices, "CPU preparation refuses an allocated NVIDIA GPU")
    return {"status": "empty", "nvidia_smi": "queried", "returncode": result.returncode, "device_nodes": []}


def safe_member(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and ".." not in p.parts and "\\" not in name,
            "Unsafe archive path")
    return p


def safe_extract(archive, target, max_bytes=8 * 1024**3):
    """Validate the complete archive before writes; links stay inside its own tree."""
    target = Path(target)
    require(not target.exists() and not target.is_symlink(), "Extraction target must be fresh")
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        require(len(members) <= 250000 and sum(m.size for m in members) <= max_bytes, "Archive exceeds bounds")
        entries = {}
        for member in members:
            name = str(safe_member(member.name))
            require(name not in entries, "Duplicate archive path")
            require(member.isdir() or member.isfile() or member.issym() or member.islnk(), "Special archive entry rejected")
            entries[name] = member
        links = {}
        for name, member in entries.items():
            for parent in PurePosixPath(name).parents:
                if str(parent) in entries:
                    require(entries[str(parent)].isdir(), "Archive file has a non-directory ancestor")
            if member.issym() or member.islnk():
                raw = PurePosixPath(member.linkname)
                require(member.linkname and not raw.is_absolute() and "\\" not in member.linkname, "External archive link")
                base = PurePosixPath(name).parent if member.issym() else PurePosixPath()
                components = []
                for part in (base / raw).parts:
                    if part == "..":
                        require(components, "External archive link")
                        components.pop()
                    elif part != ".":
                        components.append(part)
                links[name] = "/".join(components)
        resolved_links = {}
        for name, destination in links.items():
            seen = {name}
            while destination in links:
                require(destination not in seen, "Cyclic archive link")
                seen.add(destination)
                destination = links[destination]
            require(destination in entries, "Dangling archive link")
            target_member = entries[destination]
            require(target_member.isfile() or (entries[name].issym() and target_member.isdir()), "Invalid archive link target")
            resolved_links[name] = destination
        target.mkdir(parents=True)
        for name, member in sorted(entries.items(), key=lambda x: (len(PurePosixPath(x[0]).parts), x[0])):
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                destination.mkdir(exist_ok=True)
            elif member.isfile():
                with tf.extractfile(member) as source, destination.open("xb") as out:
                    shutil.copyfileobj(source, out)
                destination.chmod(member.mode & 0o777)
        for name, member in entries.items():
            destination = target / name
            if member.issym():
                destination.symlink_to(member.linkname)
            elif member.islnk():
                os.link(target / resolved_links[name], destination)
    return target


def download(url, target, expected, *, timeout=300, max_bytes=1024**3):
    pin(expected)
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname in {"raw.githubusercontent.com", "download.blender.org", "static.rust-lang.org", "static.crates.io", "github.com"}
            and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment,
            "Only approved public HTTPS source URLs supported")
    require(parsed.hostname != "github.com" or url == RELEASE_URL, "Only the pinned public release URL is approved")
    target = Path(target)
    require(not target.exists() and not target.is_symlink(), "Download target must be fresh")
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    count = 0
    h = hashlib.sha256()
    # No proxy, cookie jar, auth handler, .netrc, or signed artifact endpoints.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "RustDutyPublicCPUPrep/1"}), timeout=30) as response, target.open("xb") as out:
            require(response.status == 200, "Public download failed")
            while chunk := response.read(1024 * 1024):
                require(time.monotonic() - started < timeout, "Public download timed out")
                count += len(chunk)
                require(count <= max_bytes, "Public input exceeds bound")
                h.update(chunk)
                out.write(chunk)
        require(h.hexdigest() == expected, "Public input SHA-256 mismatch: " + target.name)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"url": url, "sha256": h.hexdigest(), "bytes": count, "elapsed_seconds": round(time.monotonic() - started, 3)}


def process_ticks(pgid, known=None):
    """Count own process group AND nested helper descendants, including child CPU."""
    processes = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(") ", 1)[1].split()
            processes[int(path.parent.name)] = (int(fields[1]), int(fields[2]), sum(int(fields[i]) for i in (11, 12, 13, 14)), int(fields[19]))
        except (OSError, ValueError, IndexError):
            continue
    selected = {pid for pid, (_, group, _, _) in processes.items() if group == pgid}
    if known is not None:
        selected |= {pid for pid, start in known.items() if pid in processes and processes[pid][3] == start}
    while True:
        children = {pid for pid, (parent, _, _, _) in processes.items() if parent in selected}
        if children <= selected:
            break
        selected |= children
    if known is not None:
        known.update({pid: processes[pid][3] for pid in selected})
    return sum(processes[pid][2] for pid in selected), selected


def terminate_group(process, known=None):
    _, descendants = process_ticks(process.pid, known)
    # Nested helper sessions still belong to this task; signal them before parent exits.
    groups = {process.pid}
    for pid in descendants:
        try:
            groups.add(os.getpgid(pid))
        except ProcessLookupError:
            pass
    groups.discard(os.getpgrp())
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for group in groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


class Runner:
    def __init__(self, root, env, inactivity=180, overall_seconds=None):
        self.root, self.env = Path(root), env
        self.inactivity, self.overall_seconds = inactivity, overall_seconds
        self.started = time.monotonic()
        self.phases = []
        (self.root / "logs").mkdir()

    def run(self, name, argv, cwd=None, *, timeout=5400, input_text=None):
        require(re.fullmatch(r"[a-z0-9_-]+", name), "Invalid phase name")
        started = time.monotonic()
        log = self.root / "logs" / (name + ".log")
        require(not log.exists(), "Duplicate phase")
        row = {"name": name, "argv": list(map(str, argv)), "cwd": str(cwd or self.root),
               "log": str(log.relative_to(self.root)), "status": "running", "timeout_seconds": timeout,
               "inactivity_seconds": self.inactivity, "exit_code": None}
        self.phases.append(row)
        save(self.root / "PHASES.json", self.phases)
        print("CPU phase: " + name, flush=True)
        process = None
        owned_descendants = {}
        try:
            with log.open("xb") as output:
                process = subprocess.Popen(row["argv"], cwd=cwd or self.root, env=self.env,
                                           stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                if input_text is not None:
                    process.stdin.write(input_text.encode())
                    process.stdin.close()
                activity, last_size, last_ticks = started, 0, 0
                while process.poll() is None:
                    time.sleep(0.5)
                    now = time.monotonic()
                    ticks, _ = process_ticks(process.pid, owned_descendants)
                    # Track helper child logs too: their CPU work need not echo to the outer log.
                    size = sum(p.stat().st_size for p in self.root.rglob("*.log") if p.is_file())
                    if size != last_size or ticks > last_ticks:
                        activity = now
                    last_size, last_ticks = size, ticks
                    if now - activity > self.inactivity:
                        raise TimeoutError("Phase inactivity limit reached: " + name)
                    if now - started > timeout:
                        raise TimeoutError("Phase deadline reached: " + name)
                    if self.overall_seconds is not None and now - self.started > self.overall_seconds:
                        raise TimeoutError("Explicit overall deadline reached")
                row["exit_code"] = process.returncode
                require(process.returncode == 0, "Phase failed: " + name + "; see " + str(log))
                row["status"] = "passed"
        except BaseException:
            row["status"] = "failed"
            if process is not None:
                terminate_group(process, owned_descendants)
                row["exit_code"] = process.returncode
            raise
        finally:
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            save(self.root / "PHASES.json", self.phases)
        return log.read_text(errors="replace").strip()


def production_inventory(source):
    files = [source / name for name in ("build.rs", "build_number.rs", "settings.cfg")]
    for directory in ("src", "ui", "profiles", "updater/src"):
        files.extend(p for p in (source / directory).rglob("*") if p.is_file())
    result = {p.relative_to(source).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(files)}
    require(len(result) == 110, "Production inventory differs from reviewed 110 files")
    return result


def transform_cargo(manifest, lock, vendor):
    doc = tomllib.loads(manifest.decode())
    require("patch" not in doc and "replace" not in doc, "Existing Cargo overrides rejected")
    require(doc["dependencies"]["wgpu"]["version"] == "=30.0.1", "Unexpected wgpu dependency")
    before = tomllib.loads(lock.decode())
    matches = [p for p in before["package"] if p["name"] == "wgpu-hal"]
    require(len(matches) == 1 and matches[0]["version"] == "30.0.1" and matches[0].get("checksum") == CRATE_SHA,
            "Expected official pinned wgpu-hal lock entry")
    blocks = lock.decode().split("[[package]]")
    for index, block in enumerate(blocks[1:], 1):
        if tomllib.loads(block).get("name") == "wgpu-hal":
            blocks[index] = "".join(line for line in block.splitlines(keepends=True) if not line.startswith(("source = ", "checksum = ")))
    new_lock = "[[package]]".join(blocks).encode()
    expected = json.loads(json.dumps(before))
    entry = next(p for p in expected["package"] if p["name"] == "wgpu-hal")
    del entry["source"]
    del entry["checksum"]
    require(tomllib.loads(new_lock.decode()) == expected, "Lockfile change exceeded one path dependency")
    new_manifest = manifest + ("\n[patch.crates-io]\nwgpu-hal = { path = " + json.dumps(str(vendor)) + " }\n").encode()
    require(tomllib.loads(new_manifest.decode())["patch"]["crates-io"]["wgpu-hal"]["path"] == str(vendor), "Unsafe manifest transform")
    return new_manifest, new_lock


def tree_manifest(root):
    rows = {}
    for path in sorted(Path(root).rglob("*")):
        require(not path.is_symlink(), "Symlink in receipt tree")
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return rows


def apply_overlay(source, vendor, patch, harness, runner):
    require(sha(patch) == PATCH_SHA and sha(harness) == HARNESS_SHA, "Reviewed overlay/harness pin mismatch")
    before = tree_manifest(vendor)
    require(before["src/gles/egl.rs"]["sha256"] == EGL_BEFORE, "Original EGL source mismatch")
    runner.run("patch-gl-context", ["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(patch)], cwd=vendor, timeout=60)
    after = tree_manifest(vendor)
    require(after["src/gles/egl.rs"]["sha256"] == EGL_AFTER, "Patched EGL source mismatch")
    require(set(before) == set(after) and all(before[k] == after[k] for k in before if k != "src/gles/egl.rs"), "Unreviewed vendor change")
    files = {}
    originals = [(source / name).read_bytes() for name in ("Cargo.toml", "Cargo.lock")]
    changes = transform_cargo(*originals, vendor)
    for name, old, new in zip(("Cargo.toml", "Cargo.lock"), originals, changes):
        (source / name).write_bytes(new)
        files[name] = {"original_sha256": digest(old), "adapted_sha256": digest(new)}
    destination = source / "examples/linux_actual_game_gl.rs"
    require(not destination.exists(), "Harness already exists")
    shutil.copyfile(harness, destination)
    return {"schema_version": 1, "kind": "isolated Linux GL4.3 dependency context experiment",
            "official_crate_sha256": CRATE_SHA, "patch_sha256": PATCH_SHA, "vendor_files": after,
            "egl_original_sha256": EGL_BEFORE, "egl_patched_sha256": EGL_AFTER,
            "files": files, "validation_flags_changed": False, "game_sources_changed": False,
            "native_execution": False}


def check_asset_result(output):
    result = json.loads((output / "ASSET_BUILD_RESULT.json").read_text())
    require(result.get("schema") == "rust-duty-public-authored-build/v1" and result.get("status") == "passed",
            "Fresh authored asset production did not pass")
    require(result.get("production_files_preserved") is True, "Authored production source preservation failed")
    require(set(result.get("groups", {})) == {"reload", "walk", "ads", "directional", "jump"}, "Missing authored groups")
    require(all(group.get("validation") == "passed" and group.get("files") for group in result["groups"].values()), "Unvalidated authored group")
    require(result.get("inputs", {}).get("source_commit") == SOURCE_COMMIT, "Authored receipt source commit differs")
    require((output / "receipt.json").read_bytes() == (output / "ASSET_BUILD_RESULT.json").read_bytes(), "Asset receipt copies differ")
    return result


def build_identity(source, executable, version, number, label, receipt_path):
    require(version == "0.1.11" and number.startswith("local.") and label == version + "+build." + number,
            "Fresh executable returned unexpected build metadata")
    return {"schema": "rust-duty-build-identity/v1", "version": version, "build_number": number,
            "display_version": label, "target": "x86_64-unknown-linux-gnu",
            "source": {"commit": SOURCE_COMMIT, "branch": "detached pinned public input", "run_id": None, "run_attempt": None, "run_url": None},
            "executable": {"name": executable.name, "bytes": executable.stat().st_size, "sha256": sha(executable)},
            "benchmark_entrypoint": {"kind": "linux_native_gl_actual_game_harness", "source_path": "examples/linux_actual_game_gl.rs",
                                     "source_sha256": sha(source / "examples/linux_actual_game_gl.rs"),
                                     "receipt_file": receipt_path.name, "receipt_sha256": sha(receipt_path)}}


def make_archive(root, members, target):
    """Portable fresh result; never includes checkout, authoring inputs, or toolchains."""
    require(not target.exists(), "Archive destination exists")
    manifest = {}
    with target.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w|") as tar:
        for name in members:
            item = root / name
            files = [item] if item.is_file() else sorted(p for p in item.rglob("*") if p.is_file())
            for path in files:
                relative = path.relative_to(root).as_posix()
                record = {"sha256": sha(path), "bytes": path.stat().st_size}
                manifest[relative] = record
                header = tarfile.TarInfo(relative)
                header.size = record["bytes"]
                header.mode = 0o755 if path.name == "vector-range" else 0o644
                with path.open("rb") as stream:
                    tar.addfile(header, stream)
    with tarfile.open(target, "r:gz") as tar:
        verified = {member.name: {"sha256": digest(tar.extractfile(member).read()), "bytes": member.size} for member in tar}
    require(verified == manifest, "Archive validation failed")
    return {"file": target.name, "sha256": sha(target), "bytes": target.stat().st_size,
            "files": len(manifest), "all_archived_file_hashes_verified": True}


def selected_sparse_paths(mode):
    return SPARSE_PATHS if mode == "regenerate" else tuple(path for path in SPARSE_PATHS if not path.startswith("assets/authoring/") and not path.endswith(".blend"))


def release_asset_overlay(archive, source):
    """Extract ONLY allowlisted assets, preserving source49 documentation and binary."""
    source = Path(source)
    require(source.is_dir() and not source.is_symlink(), "Source must be an existing real directory")
    prefixes = tuple("assets/" + group + "/" for group in ASSET_GROUPS)
    selected = []
    names = set()
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        require(len(entries) <= 5000 and sum(item.file_size for item in entries) <= 2 * 1024**3, "Public ZIP exceeds bounds")
        for item in entries:
            name = str(safe_member(item.filename))
            require(name not in names, "Duplicate ZIP path")
            names.add(name)
            filetype = stat.S_IFMT(item.external_attr >> 16)
            require(filetype in (0, stat.S_IFREG, stat.S_IFDIR), "ZIP special/link entry rejected")
            require(not (item.flag_bits & 1), "Encrypted ZIP input rejected")
            if item.is_dir() or not item.filename.startswith(prefixes):
                continue
            require(item.file_size <= 128 * 1024**2, "Asset member exceeds bound")
            require(Path(name).suffix in {".vra", ".vrs", ".vrm", ".json", ".gz", ".md"}, "Unexpected public asset member")
            target = source / name
            require(not target.is_symlink() and not any(parent.is_symlink() for parent in target.parents), "Linked asset destination rejected")
            if target.exists():
                require(target.is_file(), "Non-file asset destination")
            selected.append((item, target))
        for group in ASSET_GROUPS:
            require(any(item.filename == "assets/" + group + "/manifest.json" for item, _ in selected), "Release lacks complete group: " + group)
        records, preserved = {}, {}
        for item, target in selected:
            data = zipped.read(item)
            if target.name == "README.md" and target.exists():
                preserved[item.filename] = {"sha256": sha(target), "bytes": target.stat().st_size}
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            records[item.filename] = {"sha256": sha(target), "bytes": len(data)}
    return {"files_from_public_zip": records, "source_readmes_preserved": preserved,
            "release_executable_extracted": False, "release_ui_config_docs_extracted": False}


def verify_release_source_bindings(source, canonical_manifest):
    """Bind stored authoring hashes to independently embedded source49 contracts."""
    source = Path(source)
    bindings = {}
    groups = {"walk": "assets/authoring/locomotion/locomotion.blend", "ads": "assets/authoring/ads/ads.blend",
              "directional": "assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend",
              "jump": "assets/authoring/jump/halcyon_jump.blend"}
    for group, name in groups.items():
        manifest = json.loads((source / "assets" / group / "manifest.json").read_text())
        expected = JUMP_SHA if group == "jump" else AUTHORING_PINS[name]
        record = manifest.get("source", {})
        require(record.get("file") == name and record.get("sha256") == expected,
                "Release authoring source contract differs: " + group)
        bindings[group] = {"file": name, "sha256": expected, "basis": "independently pinned authoring source digest; source bytes not downloaded"}
    current_reload = json.loads((source / "assets/source/reload/source.json").read_text())
    release_reload = json.loads((source / "assets/reload/source.json").read_text())
    require(current_reload.get("sha256") == AUTHORING_PINS["assets/source/reload/current.blend"] and current_reload == release_reload,
            "Release reload source differs from source49 committed contract")
    bindings["reload"] = {"file": "assets/source/reload/current.blend", "sha256": current_reload["sha256"],
                          "committed_source_json_sha256": sha(source / "assets/source/reload/source.json")}
    release_canonical = json.loads((source / "assets/locomotion/manifest.json").read_text())
    require(release_canonical.get("files") == canonical_manifest.get("files") and release_canonical.get("source") == canonical_manifest.get("source"),
            "Release canonical locomotion differs from source49 source/files contract")
    bindings["locomotion"] = {"basis": "matches source49 committed canonical source and companion contracts", "files": canonical_manifest["files"]}
    return bindings


def prepare(args, root, cpu_receipt):
    env = sanitized_env(root)
    for directory in ("config", "tmp", "cargo", "downloads", "support", "matrix-tools", "evidence"):
        (root / directory).mkdir()
    (root / "empty-netrc").write_text("")
    runner = Runner(root, env, overall_seconds=args.overall_seconds)
    receipts = {"cpu_only_preflight": cpu_receipt, "public_inputs": {}, "source_commit": SOURCE_COMMIT,
                "support_commit": args.support_commit, "asset_mode": args.asset_mode, "source_root": str(root / "source"), "runtime_executed": False}
    save(root / "PREPARATION_INPUTS.json", receipts)
    def fetch(label, url, path, expected, **kw):
        receipts["public_inputs"][label] = download(url, path, expected, **kw)
        save(root / "PREPARATION_INPUTS.json", receipts)
    if args.install_system_deps:
        prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
        runner.run("system-package-index", prefix + ["apt-get", "update"], timeout=900)
        runner.run("system-libraries", prefix + ["apt-get", "install", "-y", "--no-install-recommends", *APT_PACKAGES], timeout=1800)
    require(all(shutil.which(name, path=env["PATH"]) for name in ("git", "cc", "patch", "xz", "pkg-config")),
            "Missing official system build tools; rerun with --install-system-deps")
    require(all(ctypes.util.find_library(name) for name in ("X11", "Xi", "Xfixes", "Xrender", "xkbcommon", "GL", "EGL")),
            "Missing Blender system libraries; rerun with --install-system-deps")
    source = root / "source"
    anonymous_git_preflight()
    runner.run("git-init", GIT + ["init", str(source)], timeout=30)
    runner.run("git-origin", GIT + ["-C", str(source), "remote", "add", "origin", "https://github.com/RHS059/rust_duty.git"], timeout=30)
    runner.run("git-promisor", GIT + ["-C", str(source), "config", "remote.origin.promisor", "true"], timeout=30)
    sparse_paths = selected_sparse_paths(args.asset_mode)
    runner.run("git-sparse", GIT + ["-C", str(source), "sparse-checkout", "set", "--no-cone", "--stdin"],
               input_text="\n".join("/" + p for p in sparse_paths) + "\n", timeout=30)
    runner.run("git-fetch", GIT + ["-C", str(source), "fetch", "--depth=1", "--filter=blob:none", "--no-tags",
                                   "origin", SOURCE_COMMIT], timeout=900)
    runner.run("git-checkout", GIT + ["-C", str(source), "checkout", "--detach", "FETCH_HEAD"], timeout=900)
    actual = runner.run("source-head", GIT + ["-C", str(source), "rev-parse", "HEAD"], timeout=30)
    require(actual == SOURCE_COMMIT, "Public checkout is not assigned source49")
    require(not runner.run("source-clean", GIT + ["-C", str(source), "status", "--porcelain"], timeout=30), "Source checkout is not clean")
    before = production_inventory(source)
    # The clean Git checkout is the source witness. Production files are never imported from old receipts.
    save(root / "evidence/source-before.json", before)
    if args.asset_mode == "regenerate":
        for name, expected in AUTHORING_PINS.items():
            require(sha(source / name) == expected, "Public authoring input pin mismatch: " + name)
    action = (source / ".github/actions/setup-blender/action.yml").read_text()
    require(BLENDER_URL in action and BLENDER_SHA in action and "Pillow==11.3.0" in action
            and "numpy==2.2.6 scipy==1.15.3" in action, "Pinned setup action toolchain contract changed")
    base = "https://raw.githubusercontent.com/RHS059/rust_duty/"
    support = root / "support"
    support_files = [("linux_actual_game_gl.rs", HARNESS_SHA), ("linux_gl43_context.patch", PATCH_SHA)]
    if args.asset_mode == "regenerate":
        support_files.append(("build_linux_authored_inputs.py", args.asset_helper_sha256))
    for name, expected in support_files:
        fetch(name, base + args.support_commit + "/tools/" + name, support / name, expected, max_bytes=8 * 1024**2)
    prefix = root / "rust"
    for name, expected in RUST_COMPONENTS.items():
        filename = name + "-1.99.0-x86_64-unknown-linux-gnu.tar.xz"
        archive = root / "downloads" / filename
        fetch(name, RUST_BASE + filename, archive, expected)
        unpacked = safe_extract(archive, root / ("unpack-" + name)) / filename.removesuffix(".tar.xz")
        runner.run("install-" + name, ["sh", str(unpacked / "install.sh"), "--prefix=" + str(prefix), "--disable-ldconfig"], timeout=300)
    env["PATH"] = str(prefix / "bin") + ":" + env["PATH"]
    compiler = runner.run("compiler-identity", [str(prefix / "bin/rustc"), "--version", "--verbose"], timeout=30)
    require(compiler.startswith("rustc 1.99.0 ") and "host: x86_64-unknown-linux-gnu" in compiler, "Compiler identity differs")
    (root / "evidence/compiler.txt").write_text(compiler + "\n")
    runner.run("cargo-identity", [str(prefix / "bin/cargo"), "--version", "--verbose"], timeout=30)
    runner.run("python-venv", [sys.executable, "-I", "-m", "venv", str(root / "venv")], timeout=120)
    python = root / "venv/bin/python"
    pip = [str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "--retries", "2", "--timeout", "60"]
    runner.run("host-python-dependencies", pip + ["install", "--index-url", "https://pypi.org/simple", "--only-binary=:all:",
               "--report", str(root / "evidence/host-python-install.json"), "Pillow==11.3.0", "numpy==2.2.6", "scipy==1.15.3"], timeout=900)
    env["PATH"] = str(root / "venv/bin") + ":" + env["PATH"]
    runner.run("host-python-identity", [str(python), "-I", "-c", "import PIL,numpy,scipy; assert (PIL.__version__,numpy.__version__,scipy.__version__)==('11.3.0','2.2.6','1.15.3'); print(PIL.__version__,numpy.__version__,scipy.__version__)"], timeout=30)
    if args.asset_mode == "regenerate":
        jump = root / "jump-source/assets/authoring/jump"
        fetch("jump-authoring", base + JUMP_COMMIT + "/assets/authoring/jump/halcyon_jump.blend", jump / "halcyon_jump.blend", JUMP_SHA, max_bytes=16 * 1024**2)
        archive = root / "downloads/blender.tar.xz"
        fetch("blender", BLENDER_URL, archive, BLENDER_SHA)
        blender_root = safe_extract(archive, root / "blender-unpacked") / "blender-4.3.2-linux-x64"
        blender = blender_root / "blender"
        blender_python = blender_root / "4.3/python/bin/python3.11"
        runner.run("blender-ensurepip", [str(blender_python), "-I", "-m", "ensurepip"], timeout=120)
        runner.run("blender-python-dependencies", [str(blender_python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
                   "--index-url", "https://pypi.org/simple", "--only-binary=:all:", "--retries", "2", "--timeout", "60",
                   "--report", str(root / "evidence/blender-python-install.json"), "Pillow==11.3.0"], timeout=900)
        runner.run("blender-identity", [str(blender), "--background", "--disable-autoexec", "--python-exit-code", "1", "--python-expr",
                   "import bpy,PIL,numpy; assert bpy.app.version==(4,3,2) and PIL.__version__=='11.3.0'; print(bpy.app.version_string,PIL.__version__,numpy.__version__)"], timeout=60)
        runner.run("materialize-canonical", [str(python), str(source / "tools/package_game.py"), "materialize", "--root", str(source)], cwd=source)
        runner.run("fetch-sampler", ["cargo", "fetch", "--locked"], cwd=source, timeout=1800)
        runner.run("build-cpu-sampler", ["cargo", "build", "--offline", "--locked", "--release", "--no-default-features", "--example", "sample_viewmodel_clip"], cwd=source)
        sampler = root / "target/release/examples/sample_viewmodel_clip"
        assets_output = root / "authored-output"
        runner.run("produce-authored-inputs", [str(python), str(support / "build_linux_authored_inputs.py"), "--source", str(source),
                   "--blender", str(blender), "--sampler", str(sampler), "--jump-source-dir", str(jump), "--output", str(assets_output)], timeout=7 * 5400)
        asset_receipt = check_asset_result(assets_output)
        shutil.copyfile(assets_output / "ASSET_BUILD_RESULT.json", root / "evidence/authored-assets.json")
    else:
        archive = root / "downloads/public-v0.1.9-linux.zip"
        fetch("public-release-assets", RELEASE_URL, archive, RELEASE_SHA, max_bytes=RELEASE_BYTES)
        require(archive.stat().st_size == RELEASE_BYTES, "Public release archive size differs")
        canonical_manifest = json.loads((source / "assets/locomotion/manifest.json").read_text())
        overlay_assets = release_asset_overlay(archive, source)
        bindings = verify_release_source_bindings(source, canonical_manifest)
        validation = json.loads(runner.run("validate-public-release-assets", [str(python), "-B", str(source / "tools/package_game.py"), "verify", "--root", str(source), "--require-generated"], cwd=source))
        asset_receipt = {"schema": "rust-duty-public-release-assets/v1", "status": "passed", "source_commit": SOURCE_COMMIT,
                         "origin": {"url": RELEASE_URL, "sha256": RELEASE_SHA, "bytes": RELEASE_BYTES},
                         "asset_mode": "public-release", "new_parity_measured": False, "freshly_generated": False,
                         "release_executable_used": False, "production_validation": validation, "source_contract_bindings": bindings, **overlay_assets,
                         "authoring_source_bytes_downloaded": False,
                         "source_binding": "Source49 production validators recheck stored source hashes and successful historical parity records; no new authoring/parity execution",
                         "comparison_limits": "Alternate public-release asset provenance: 15 nonreload raw companions previously matched the frozen fixture; 8 of 12 reload companions differ. No frozen binary or whole-asset identity claim."}
        save(root / "evidence/authored-assets.json", asset_receipt)
    archive = root / "downloads/wgpu-hal-30.0.1.crate"
    fetch("wgpu-hal", "https://static.crates.io/crates/wgpu-hal/wgpu-hal-30.0.1.crate", archive, CRATE_SHA, max_bytes=16 * 1024**2)
    vendor = safe_extract(archive, root / "vendor") / "wgpu-hal-30.0.1"
    overlay = apply_overlay(source, vendor, support / "linux_gl43_context.patch", support / "linux_actual_game_gl.rs", runner)
    save(root / "evidence/dependency-overlay.json", overlay)
    # Patched manifest and lock retain all existing package versions/checksums except the one path crate.
    runner.run("fetch-gl-dependencies", ["cargo", "fetch", "--locked"], cwd=source, timeout=1800)
    command = ["cargo", "build", "--offline", "--locked", "--release", "--no-default-features", "--features", "wgpu-runtime", "--example", "linux_actual_game_gl"]
    runner.run("build-gl-harness", command, cwd=source)
    runner.run("fetch-updater-licenses", ["cargo", "fetch", "--manifest-path", str(source / "updater/Cargo.toml"), "--locked"], cwd=source, timeout=1800)
    runner.run("collect-updater-licenses", [str(python), str(source / "tools/collect_updater_licenses.py")], cwd=source)
    executable = root / "target/release/examples/linux_actual_game_gl"
    with executable.open("rb") as stream:
        require(stream.read(4) == b"\x7fELF", "Fresh harness is not Linux ELF")
    metadata = {}
    for key in ("version", "number", "label"):
        metadata[key] = runner.run("build-" + key, [str(executable), "--build-" + key], cwd=source, timeout=30)
    (source / "bin").mkdir()
    shutil.copy2(executable, source / "bin/vector-range")
    package = root / "package"
    stage_code = "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]+'/tools'); import package_game; print(json.dumps(package_game.stage(Path(sys.argv[1]),'bin/vector-range',Path(sys.argv[2]),require_generated=True),sort_keys=True))"
    staged = runner.run("stage-complete-package", [str(python), "-I", "-c", stage_code, str(source), str(package)], cwd=source)
    save(root / "evidence/package-validation.json", json.loads(staged))
    after = production_inventory(source)
    save(root / "evidence/source-after.json", after)
    require(after == before, "Production source changed during CPU preparation")
    source_identity = {"schema": "rust-duty-linux-actual-game-source/v1", "source_commit": SOURCE_COMMIT,
                       "production_files_byte_identical_to_commit": True, "production_files": after,
                       "harness": {"source_path": "examples/linux_actual_game_gl.rs", "sha256": sha(source / "examples/linux_actual_game_gl.rs")}}
    save(root / "evidence/source-identity.json", source_identity)
    receipt = {"schema": "rust-duty-actual-game-harness/v1", "kind": "linux_native_gl_actual_game_harness",
               "source_commit": SOURCE_COMMIT, "source_path": "examples/linux_actual_game_gl.rs", "source_sha256": HARNESS_SHA,
               "executable_sha256": sha(package / "vector-range"), "build_label": metadata["label"],
               "production_modules_byte_identical": True, "toolchain": compiler, "dependency_overlay": overlay,
               "build": {"command": " ".join(command), "profile": "release", "opt_level": 3, "lto": "thin", "codegen_units": 1,
                         "strip": True, "default_features": False, "features": ["wgpu-runtime"], "audio_enabled": False},
               "authored_assets": {"receipt_sha256": sha(root / "evidence/authored-assets.json"), "status": asset_receipt["status"], "mode": args.asset_mode, "new_parity_measured": args.asset_mode == "regenerate"},
               "execution_status": "fresh CPU-only linked build and production package validation; no window/GPU execution",
               "claim_limits": ["isolated test harness entrypoint", "Linux GL context overlay", "audio disabled", "native NVIDIA X11 surface and Record remain unproven", "no old binary/archive identity claim"]}
    receipt_path = package / "ACTUAL_GAME_HARNESS_RECEIPT.json"
    save(receipt_path, receipt)
    save(package / "BUILD_IDENTITY.json", build_identity(source, package / "vector-range", metadata["version"], metadata["number"], metadata["label"], receipt_path))
    for name, expected in MATRIX_FILES.items():
        fetch(name, base + MATRIX_COMMIT + "/tools/" + name, root / "matrix-tools" / name, expected, max_bytes=1024**2)
    matrix = root / "matrix-tools/performance_matrix.py"
    witness = root / "source-witness"
    runner.run("export-fresh-witness", [str(python), str(matrix), "export-witness", "--repository", str(source),
               "--harness", str(source / "examples/linux_actual_game_gl.rs"), "--output", str(witness)], cwd=source, timeout=60)
    witness_sha = sha(witness / "SOURCE_WITNESS.json")
    verify_code = "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); import performance_matrix as m; s=m.artifact_source(Path(sys.argv[2]),sys.argv[3]); print(json.dumps(m.package_identity(Path(sys.argv[4]),s,'gl-harness'),sort_keys=True))"
    identity = json.loads(runner.run("validate-fresh-identity", [str(python), "-I", "-c", verify_code, str(matrix.parent), str(witness), witness_sha, str(package / "vector-range")], timeout=60))
    save(root / "evidence/matrix-package-identity.json", identity)
    for kind in ("smoke", "pilot"):
        runner.run("prepare-" + kind, [str(python), str(matrix), "prepare", "--renderer", "gl-harness", "--" + kind,
                   "--source-witness", str(witness), "--witness-sha256", witness_sha, "--output", str(root / (kind + "-plan.json"))], timeout=60)
    expected_adapter = {"backend": "gl", "name": "NVIDIA A100-SXM4-40GB/PCIe/SSE2", "vendor_id": 4318, "device_id": 0, "device_type": "Other"}
    save(root / "expected-a100.json", {"schema": "rust-duty-graphics-device/v1", "adapter": expected_adapter})
    save(root / "PACKAGE_FILES.json", tree_manifest(package))
    expectations = {"schema": "rust-duty-fresh-linux-matrix-inputs/v1", "source_commit": SOURCE_COMMIT, "asset_mode": args.asset_mode,
                    "executable_sha256": sha(package / "vector-range"), "source_witness_sha256": witness_sha,
                    "build_identity_sha256": sha(package / "BUILD_IDENTITY.json"), "harness_receipt_sha256": sha(receipt_path),
                    "package_manifest_sha256": sha(root / "PACKAGE_FILES.json"), "adjacent_files_digest": identity["adjacent_files_digest"],
                    "plans": {kind: sha(root / (kind + "-plan.json")) for kind in ("smoke", "pilot")},
                    "matrix_tools": MATRIX_FILES, "runtime_controller": "Not supplied: frozen run_colab_matrix.py pins a different executable; integrate these fresh expectations before any runtime",
                    "runtime_executed": False, "gpu_gate": "Still required on the later GPU host"}
    save(root / "NEW_EXPECTATIONS.json", expectations)
    receipts["production_files_preserved"] = production_inventory(source) == before
    require(receipts["production_files_preserved"], "Production source preservation failed")
    receipts["cpu_only_postflight"] = gpu_gate()
    save(root / "PREPARATION_INPUTS.json", receipts)
    archive_result = None
    if args.archive:
        archive_result = make_archive(root, ["package", "source-witness", "matrix-tools", "smoke-plan.json", "pilot-plan.json", "expected-a100.json",
                                            "PACKAGE_FILES.json", "NEW_EXPECTATIONS.json", "PREPARATION_INPUTS.json", "PHASES.json", "evidence", "logs"], root / "fresh-linux-actual-game.tar.gz")
        save(root / "TRANSPORT_RECEIPT.json", archive_result)
    return {"status": "prepared", "source_commit": SOURCE_COMMIT, "asset_mode": args.asset_mode, "build_label": metadata["label"],
            "production_files_preserved": True, "production_file_count": len(before), "package": str(package),
            "new_expectations": expectations, "archive": archive_result, "runtime_executed": False,
            "claim": "Fresh package prepared; smoke/pilot plans have not run"}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs-root", type=Path, default=Path("/content/rust-duty-cpu-runs"))
    p.add_argument("--asset-mode", choices=("public-release", "regenerate"), default="public-release", help="Public-release revalidates pinned existing assets; regenerate executes all five fresh producers")
    p.add_argument("--support-commit", help="Immutable public commit containing this proposal's support tools")
    p.add_argument("--asset-helper-sha256", help="Separately supplied SHA-256 of published authored-input helper")
    p.add_argument("--install-system-deps", action="store_true", help="Install official distro packages needed by committed Blender action and Rust")
    p.add_argument("--archive", action="store_true", help="Export verified fresh package/plans/receipts, never publish")
    p.add_argument("--overall-seconds", type=int, help="Optional explicit overall subprocess budget; no implicit total build estimate")
    p.add_argument("--dry-run", action="store_true", help="Print pinned preparation contract without writes or network")
    p.add_argument("--self-check", action="store_true", help="Check built-in pins without network, builds, or GPU query")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    pin(SOURCE_COMMIT, 40)
    for value in [RELEASE_SHA, JUMP_SHA, HARNESS_SHA, PATCH_SHA, CRATE_SHA, BLENDER_SHA, *RUST_COMPONENTS.values(), *MATRIX_FILES.values(), *AUTHORING_PINS.values()]:
        pin(value)
    if args.self_check or args.dry_run:
        print(json.dumps({"status": "self-check-passed" if args.self_check else "dry-run", "source_commit": SOURCE_COMMIT,
                          "cpu_only": True, "gpu_inventory_must_be_empty_before_setup": True, "source_mutation": "new disposable checkout only",
                          "rust": "1.99.0", "blender": "4.3.2", "host_python_packages": ["Pillow==11.3.0", "numpy==2.2.6", "scipy==1.15.3"],
                          "support_commit_required_for_execution": True, "asset_mode": args.asset_mode, "asset_helper_sha256_required_for_execution": args.asset_mode == "regenerate",
                          "fresh_authored_groups": ["reload", "walk", "ads", "directional", "jump"] if args.asset_mode == "regenerate" else [], "producer_limit_seconds": 5400,
                          "inactivity_seconds": 180, "progress": "log growth or Linux process group/descendant CPU time",
                          "runtime_executed": False, "cold_build_duration": "unmeasured"}, indent=2))
        return 0
    pin(args.support_commit, 40)
    if args.asset_mode == "regenerate":
        pin(args.asset_helper_sha256)
    require(args.overall_seconds is None or args.overall_seconds > 0, "Overall cap must be positive")
    require(sys.version_info >= (3, 11) and platform.system() == "Linux" and platform.machine() == "x86_64", "Requires Linux x86_64 Python3.11+")
    cpu_receipt = gpu_gate()  # Must precede mkdir, downloads, install, or other work.
    parent = args.runs_root.absolute()
    require(not parent.is_symlink() and not any(p.is_symlink() for p in parent.parents), "Run root must not traverse symlinks")
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="run-", dir=parent)).resolve()
    started = time.monotonic()
    result = {"status": "running", "run_root": str(root), "runtime_executed": False}
    save(root / "RESULT.json", result)
    def interrupted(signum, frame):
        raise InterruptedError("CPU preparation received signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try:
        result.update(prepare(args, root, cpu_receipt))
    except BaseException as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save(root / "RESULT.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
