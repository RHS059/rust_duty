# Windows-native OpenGL reference for strict renderer parity

Status: the official package bytes and PE import closure have been inspected;
Windows loading, native rendering and authored parity remain **unverified**.
Staging files is not a renderer acceptance pass.

Linux verification on 2026-10-05 used the actual helper under PowerShell 7.6.6:
all fourteen pinned offline archives staged successfully, including fifteen
DLLs, their actual PE import closure and twenty-eight license files. Fourteen
negative controls rejected existing destinations, bad schema/URLs/hashes,
traversal, missing or altered imports, duplicate/unused DLLs, a different driver,
the wrong PE machine and delayed imports. The original archive cache and
existing-file sentinels stayed unchanged. Windows and the helper's online
download mode are not covered by that offline staging result.

## Purpose and boundaries

The existing Linux-legacy versus Windows-DX12 comparison changes the renderer
and platform math provider together. Authored receiver mapping calls `f32::atan2`;
Rust documents its [platform-dependent precision](https://doc.rust-lang.org/std/primitive.f32.html#method.atan2).
The reload-return investigation reproduced the observed anchor differences by
changing only a CPU process's `atan2f` provider. A native pair on one Windows
runtime isolates renderer behavior without changing simulation or animation math.

Use the **same combined-feature executable**, source revision, settings, assets,
capture rates, Windows runtime and working directory for both backends. Keep the
existing exact recursive gameplay/time comparison and sequence/image validators.
Do not round telemetry, omit fields, relax tolerances, override shader/version
strings, or retrospectively mark the old cross-platform failure as passed.

This helper stages test-runtime files only. It does not execute a downloaded DLL,
run the game, install a driver, modify the registry, change PATH/security, replace
System32 files, or add dependencies to distributed game packages. Native image,
landmark and hardware-playtest requirements remain separate.

## Probe the stock Windows runtime first

Build the intended revision once:

```powershell
cargo build --locked --release --no-default-features --features legacy-macroquad,wgpu-runtime --bin vector-range
New-Item -ItemType Directory evidence/stock-gl-probe
./target/release/vector-range.exe --renderer=gl --no-update --procedural-weapon --reference-viewport --capture --output=evidence/stock-gl-probe/stock-gl.png
python tools/verify_capture_telemetry.py validate evidence/stock-gl-probe --expected-backend OpenGl
```

Run through a bounded process wrapper and retain exit code, stdout, stderr and
the actual PNG/sidecar. Inspect the PNG as well as successful shader/context
initialization. This short procedural capture establishes startup feasibility;
it is not the authored reference. The `renderer_contract` example is DX12-only.
Never add `--force-fallback-adapter` to `--renderer=gl`: the production dispatcher
correctly rejects that combination.

Record the real `OpenGl` backend/adapter. Stock availability must be established
by this probe, not inferred from the Windows runner's GPU name. On failure,
retain the exact context/shader error before trying the app-local route.

## Why app-local Mesa is a supported candidate

The locked miniquad 0.4.8 Windows loader uses `LoadLibraryA("opengl32.dll")`, not
a hard-coded System32 path. Its WGL path requires `WGL_ARB_pixel_format`,
`WGL_ARB_create_context` and `WGL_ARB_create_context_profile`, then attempts
OpenGL 3.2 with a 2.1 fallback. Merely finding old generic GL functions is not
enough to pass this context contract.

[Mesa's official llvmpipe instructions](https://docs.mesa3d.org/drivers/llvmpipe.html)
support placing `opengl32.dll` and `libgallium_wgl.dll` beside the application.
[Windows loader rules](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)
normally search the executable directory before System32, subject to earlier
loaded-module/KnownDLL rules. Verify actual loaded module paths on Windows;
copying files alone does not prove selection.

The inspected Mesa 26.2.4 WGL source selects an explicit `GALLIUM_DRIVER` first
and stops if it fails. Set these **child-process-only** variables:

```text
GALLIUM_DRIVER=llvmpipe
LIBGL_ALWAYS_SOFTWARE=true
```

With that explicit driver, the source does not fall through to zink, D3D12 or
another renderer. No Vulkan execution or version/extension override is needed.

## Pinned runtime and provenance

[`tools/windows_gl_reference_lock.json`](../tools/windows_gl_reference_lock.json)
pins **Mesa 26.2.4-1**, thirteen dependency packages, and the complete fifteen-DLL
x86-64 static-import closure, totaling **180,069,633 bytes**. Every package URL,
archive SHA-256, member name, DLL SHA-256, size, PE import and license file is
recorded. Do not replace the pins with a rolling `pacman -S` invocation.

The primary [MSYS2 Mesa package](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-mesa)
archive is:

```text
https://repo.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-mesa-26.2.4-1-any.pkg.tar.zst
SHA256 82a30042848b6393f2a21cdee66b164e4cf4fe15a9721a5f1d1c7280e004ebdc
```

The manifest uses the [documented official MSYS2 main server](https://www.msys2.org/docs/mirrors/),
avoiding geo-redirector variability. Failed downloads or digest mismatches must
fail closed, not select a newer package silently.

The flat app-local layout is:

```text
vector-range.exe             # copied separately, exact built executable
opengl32.dll
libgallium_wgl.dll
libLLVM-22.dll
libSPIRV-Tools.dll
libstdc++-6.dll
libgcc_s_seh-1.dll
libwinpthread-1.dll
libsystre-0.dll
libtre-5.dll
libintl-8.dll
libiconv-2.dll
libffi-8.dll
libxml2-16.dll
zlib1.dll
libzstd.dll
licenses/
windows_gl_reference_lock.json
staging-receipt.json
```

The measured closure contains no Vulkan loader/ICD, `libglapi.dll`, MSYS runtime
or D3D12-on-OpenGL module. SPIRV-Tools is a compiler-library import here, not a
Vulkan execution request. Windows/UCRT/API-set imports stay Windows-supplied;
never bundle `ucrtbase.dll`, API-set DLLs, `gdi32.dll` or other system DLLs.
This preserves the game's Windows math provider.

## Stage without changing the machine

Requirements: PowerShell **7.2+**, HTTPS access to the pinned official packages,
and `tar.exe` with Zstandard support. An existing offline package directory can
be used instead. Staging also runs on Linux with PowerShell and `tar`, but cannot
establish Windows rendering compatibility.

```powershell
New-Item -ItemType Directory evidence -Force
pwsh -NoProfile -File tools/stage_windows_gl_reference.ps1 `
  -Manifest tools/windows_gl_reference_lock.json `
  -OutputDirectory evidence/gl-reference-runtime
Copy-Item target/release/vector-range.exe evidence/gl-reference-runtime/vector-range.exe
Get-FileHash target/release/vector-range.exe,evidence/gl-reference-runtime/vector-range.exe -Algorithm SHA256
```

The helper requires an explicit manifest/output, an existing output parent and
a **new** output directory. It preserves existing destinations and writes into
a unique sibling temporary directory. Only after all validation succeeds does
it atomically publish the runtime. Failed work removes only its own temporary
tree, never an existing output or supplied package directory.

It checks package/member hashes and sizes; reads PE headers as data; requires
x86-64 DLLs; rejects unsupported delayed imports; compares actual PE imports
to the lock; and verifies every staged DLL is reachable from `opengl32.dll` with
no unresolved non-Windows dependency or unused extra DLL. License files are
preserved. The receipt records the input manifest digest and explicitly says
that native rendering was not performed.

For offline operation, add `-PackageDirectory ABS_ARCHIVE_DIRECTORY`. That
directory is read-only to the helper and must contain every exact filename in
the manifest's `packages[].archive`. Missing files fail; offline mode never
falls back to a network download. Package archives are not executed.

If the available tar cannot read Zstandard, report the extractor prerequisite.
Do not change Windows DLL search/security settings to compensate for an
incomplete extraction. This setup is validation tooling, not a distribution
or packaging change.

## Native app-local probe and authored comparison

Use the copied executable's **same SHA-256**. Apply the two environment values
above only to its child process, run the stock-probe command with a fresh output
directory, and require actual `backend=OpenGl` plus an adapter containing
`llvmpipe`. Record loaded DLL paths and hashes; reject an unexpected driver or
incomplete capture. Restore any parent environment values afterward.

After that native probe passes, capture both authored paths from this same
executable/runtime directory, using explicit absolute asset/settings paths:

```text
vector-range.exe --renderer=gl --no-update --reference-viewport --animation-manifest=ABS_ASSETS/animations.cfg --settings=ABS_SETTINGS --capture-sequence=gameplay-return --capture-hz=60 --output=NEW_LEGACY_RETURN
vector-range.exe --renderer=dx12 --force-fallback-adapter --no-update --reference-viewport --animation-manifest=ABS_ASSETS/animations.cfg --settings=ABS_SETTINGS --capture-sequence=gameplay-return --capture-hz=60 --output=NEW_DX12_RETURN
python tools/verify_capture_telemetry.py compare NEW_LEGACY_RETURN NEW_DX12_RETURN
```

Also run the existing reload-return validator and finite/image checks on both
captures. Extend the paired design to the original full suite; keep each
scenario's explicit sampling rate or existing 60000/1001 default unchanged.
Preserve raw artifacts, source/executable/input hashes, rustc/LLVM/target and
runner-image identity. Existing image, orientation and landmark checks remain
required. A staging receipt or CPU-only replay cannot replace these native
results.

## Independent native probe

The separate `windows-gl-reference-probe.yml` workflow builds one binary with
both renderer features and runs the procedural OpenGL probe. It validates the
staged pinned DLL bytes, actual OpenGl/llvmpipe startup identity, matching PNG
sidecar, nonempty 960x540 image and clean process exit within 180 seconds.
The report explicitly records `loaded_modules_verified: false`: it does not
inspect the process module list, so staging integrity is not proof of which DLL
paths Windows loaded. This feasibility check is not full authored parity.
