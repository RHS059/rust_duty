#!/usr/bin/env python3
"""A100 preparation implementation. Frozen CPU frontend is never invoked.

Reuse only its neutral pinned fetch/build helpers. No monkeypatching or GPU hiding.
The duplicate preparation orchestration is intentionally explicit to freeze the
currently published CPU experiment. Public-release is the sole A100 asset mode.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import ctypes.util
import re
import time

CPU_HELPERS_SHA = "ac77ab291e5fb1abd6607a41793337a9fc51a88dc293db506f8e8ea7154e4296"
CPU_HELPERS = Path(__file__).with_name("prepare_linux_actual_game.py")
if CPU_HELPERS.is_symlink() or hashlib.sha256(CPU_HELPERS.read_bytes()).hexdigest() != CPU_HELPERS_SHA:
    raise ValueError("Frozen public CPU helper bytes changed")
spec = importlib.util.spec_from_file_location("frozen_cpu_helpers", CPU_HELPERS)
neutral = importlib.util.module_from_spec(spec)
spec.loader.exec_module(neutral)
# Explicit neutral API. In particular, do not import its GPU gate, sanitized_env,
# prepare, or main functions. The separate A100 guard is mandatory below.
from_types = ("require digest sha save pin anonymous_git_preflight download safe_extract "
              "Runner production_inventory selected_sparse_paths tree_manifest "
              "check_asset_result release_asset_overlay verify_release_source_bindings "
              "apply_overlay build_identity make_archive process_ticks terminate_group "
              "SOURCE_COMMIT JUMP_COMMIT JUMP_SHA RELEASE_URL RELEASE_SHA RELEASE_BYTES "
              "HARNESS_SHA PATCH_SHA CRATE_SHA BLENDER_URL BLENDER_SHA RUST_BASE "
              "RUST_COMPONENTS AUTHORING_PINS MATRIX_COMMIT MATRIX_FILES APT_PACKAGES GIT").split()
for name in from_types:
    globals()[name] = getattr(neutral, name)

A100_NAME = "NVIDIA A100-SXM4-40GB"
X11_PACKAGES = ("xvfb", "openbox", "xdotool")
X11_TOOLS = ("Xvfb", "openbox", "xdotool")
ADAPTER = {"backend": "gl", "name": "NVIDIA A100-SXM4-40GB/PCIe/SSE2",
           "vendor_id": 4318, "device_id": 0, "device_type": "Other"}


def preparation_tool_hashes():
    return {name: sha(Path(__file__).with_name(name)) for name in
            ("prepare_linux_actual_game.py", "a100_public_build.py", "prepare_public_a100.py", "run_public_a100_matrix.py", "prepare_a100_text_export.py")}


def a100_gate(run=subprocess.run, which=shutil.which):
    command = which("nvidia-smi", path="/usr/local/bin:/usr/bin:/bin:/usr/lib64-nvidia/bin")
    require(command is not None, "A100 inventory unavailable; no fallback")
    result = run([command, "--query-gpu=index,name,uuid,pci.device_id,driver_version,memory.total", "--format=csv,noheader,nounits"],
                 capture_output=True, text=True, timeout=20,
                 env={"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib64-nvidia/bin", "LANG": "C"})
    require(result.returncode == 0, "A100 inventory query failed")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    require(len(lines) == 1, "Require exactly one A100 GPU; no fallback")
    row = [value.strip() for value in lines[0].split(",")]
    require(len(row) == 6 and row[0] == "0" and row[1] == A100_NAME and row[2].startswith("GPU-")
            and row[3].lower().endswith("10de") and row[4] and 39000 <= int(row[5]) <= 42000,
            "Require exactly NVIDIA A100-SXM4-40GB with NVIDIA PCI identity and 40GB inventory")
    return {"status": "verified", "host_kind": A100_NAME, "gpus": [dict(zip(
        ("index", "name", "uuid", "pci_device_id", "driver_version", "memory_mib"), row))], "raw_inventory": result.stdout}


def public_env(root):
    """Credential-free build environment with visible, independently verified GPU."""
    root = Path(root)
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib64-nvidia/bin",
        "XDG_CONFIG_HOME": str(root / "config"), "NETRC": str(root / "empty-netrc"),
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(root / "tmp"),
        "TMP": str(root / "tmp"), "TEMP": str(root / "tmp"),
        "CARGO_HOME": str(root / "cargo"), "CARGO_TARGET_DIR": str(root / "target"),
        "RUSTUP_HOME": str(root / "rustup-unused"), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
        "GCM_INTERACTIVE": "never", "GIT_LFS_SKIP_SMUDGE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "CI": "true", "CARGO_NET_RETRY": "2", "CARGO_HTTP_TIMEOUT": "60", "CARGO_HTTP_LOW_SPEED_LIMIT": "1000",
    }
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    return env


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
        print("A100 phase: " + name, flush=True)
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


def prepare_a100(args, root, host_receipt):
    require(args.asset_mode == "public-release", "A100 proposal only authorizes public-release assets")
    env = public_env(root)
    for directory in ("config", "tmp", "cargo", "downloads", "support", "matrix-tools", "evidence"):
        (root / directory).mkdir()
    (root / "empty-netrc").write_text("")
    runner = Runner(root, env, overall_seconds=args.work_seconds)
    receipts = {"host_kind": "NVIDIA A100-SXM4-40GB", "a100_preflight": host_receipt, "public_inputs": {}, "source_commit": SOURCE_COMMIT,
                "support_commit": args.support_commit, "asset_mode": args.asset_mode, "source_root": str(root / "source"), "runtime_executed": False}
    save(root / "PREPARATION_INPUTS.json", receipts)
    runner.run("a100-full-inventory", ["nvidia-smi"], timeout=20)
    runner.run("host-lscpu", ["lscpu"], timeout=20)
    def fetch(label, url, path, expected, **kw):
        receipts["public_inputs"][label] = download(url, path, expected, **kw)
        save(root / "PREPARATION_INPUTS.json", receipts)
    if args.install_system_deps:
        prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
        runner.run("system-package-index", prefix + ["apt-get", "update"], timeout=900)
        runner.run("system-libraries", prefix + ["apt-get", "install", "-y", "--no-install-recommends", *APT_PACKAGES, *X11_PACKAGES], timeout=1800)
    require(all(shutil.which(name, path=env["PATH"]) for name in ("git", "cc", "patch", "xz", "pkg-config", *X11_TOOLS)),
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
    action = (source / ".github/actions/setup-blender/action.yml").read_text()
    require(BLENDER_URL in action and BLENDER_SHA in action and "Pillow==11.3.0" in action
            and "numpy==2.2.6 scipy==1.15.3" in action, "Pinned setup action toolchain contract changed")
    base = "https://raw.githubusercontent.com/RHS059/rust_duty/"
    support = root / "support"
    support_files = [("linux_actual_game_gl.rs", HARNESS_SHA), ("linux_gl43_context.patch", PATCH_SHA)]
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
    runner.run("python-venv", ["/usr/bin/python3.12", "-I", "-m", "venv", str(root / "venv")], timeout=120)
    python = root / "venv/bin/python"
    pip = [str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "--retries", "2", "--timeout", "60"]
    runner.run("host-python-dependencies", pip + ["install", "--index-url", "https://pypi.org/simple", "--only-binary=:all:",
               "--report", str(root / "evidence/host-python-install.json"), "Pillow==11.3.0", "numpy==2.2.6", "scipy==1.15.3"], timeout=900)
    env["PATH"] = str(root / "venv/bin") + ":" + env["PATH"]
    runner.run("host-python-identity", [str(python), "-I", "-c", "import PIL,numpy,scipy; assert (PIL.__version__,numpy.__version__,scipy.__version__)==('11.3.0','2.2.6','1.15.3'); print(PIL.__version__,numpy.__version__,scipy.__version__)"], timeout=30)
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
    linkage = runner.run("executable-linkage", ["ldd", str(executable)], timeout=20)
    require("not found" not in linkage, "Fresh executable shared library missing")
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
    require(after == before, "Production source changed during A100 host preparation")
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
               "execution_status": "fresh linked build on verified A100 host; production package validated; no window/game execution yet",
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
    identity = json.loads(runner.run("validate-fresh-identity", [str(python), "-I", "-B", "-c", verify_code, str(matrix.parent), str(witness), witness_sha, str(package / "vector-range")], timeout=60))
    save(root / "evidence/matrix-package-identity.json", identity)
    for kind in ("smoke", "pilot"):
        runner.run("prepare-" + kind, [str(python), str(matrix), "prepare", "--renderer", "gl-harness", "--" + kind, "--warmup-seconds", "10" if kind == "smoke" else "15", "--sample-seconds", "10" if kind == "smoke" else "30",
                   "--source-witness", str(witness), "--witness-sha256", witness_sha, "--output", str(root / (kind + "-plan.json"))], timeout=60)
    expected_adapter = {"backend": "gl", "name": "NVIDIA A100-SXM4-40GB/PCIe/SSE2", "vendor_id": 4318, "device_id": 0, "device_type": "Other"}
    save(root / "expected-a100.json", {"schema": "rust-duty-graphics-device/v1", "adapter": expected_adapter})
    save(root / "PACKAGE_FILES.json", tree_manifest(package))
    expectations = {"schema": "rust-duty-fresh-linux-matrix-inputs/v1", "source_commit": SOURCE_COMMIT, "asset_mode": args.asset_mode,
                    "executable_sha256": sha(package / "vector-range"), "source_witness_sha256": witness_sha,
                    "build_identity_sha256": sha(package / "BUILD_IDENTITY.json"), "harness_receipt_sha256": sha(receipt_path),
                    "package_manifest_sha256": sha(root / "PACKAGE_FILES.json"), "adjacent_files_digest": identity["adjacent_files_digest"],
                    "expected_adapter_sha256": sha(root / "expected-a100.json"), "preparation_tools": preparation_tool_hashes(),
                    "plans": {kind: sha(root / (kind + "-plan.json")) for kind in ("smoke", "pilot")},
                    "matrix_tools": MATRIX_FILES, "runtime_controller": "run_public_a100_matrix.py; separate expectations digest required", "host_kind": "NVIDIA A100-SXM4-40GB",
                    "runtime_executed": False, "gpu_gate": "Exact A100 inventory verified before and after this build; runtime selection still requires observed GL fingerprint"}
    receipts["production_files_preserved"] = production_inventory(source) == before
    require(receipts["production_files_preserved"], "Production source preservation failed")
    receipts["a100_postflight"] = a100_gate()
    require(receipts["a100_postflight"]["gpus"] == host_receipt["gpus"], "A100 inventory changed during preparation")
    save(root / "PREPARATION_INPUTS.json", receipts)
    expectations["preparation_inputs_sha256"] = sha(root / "PREPARATION_INPUTS.json")
    expectations["evidence_files"] = tree_manifest(root / "evidence")
    save(root / "NEW_EXPECTATIONS.json", expectations)
    archive_result = None
    if args.archive:
        archive_result = make_archive(root, ["package", "source-witness", "matrix-tools", "smoke-plan.json", "pilot-plan.json", "expected-a100.json",
                                            "PACKAGE_FILES.json", "NEW_EXPECTATIONS.json", "PREPARATION_INPUTS.json", "PHASES.json", "evidence", "logs"], root / "fresh-linux-actual-game.tar.gz")
        save(root / "TRANSPORT_RECEIPT.json", archive_result)
    return {"status": "prepared", "source_commit": SOURCE_COMMIT, "asset_mode": args.asset_mode, "build_label": metadata["label"],
            "production_files_preserved": True, "production_file_count": len(before), "package": str(package),
            "new_expectations": expectations, "archive": archive_result, "runtime_executed": False,
            "claim": "Fresh package prepared; smoke/pilot plans have not run"}

