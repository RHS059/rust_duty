# Finite probe input preparation contract

`prepare_finite_probe_inputs.py` is an offline preparer/verifier. It does not
retrieve artifacts, run Cargo/Rust, launch retained executables, or decide
native/profile acceptance. The Windows workflow and runner own execution.

## Exact source and scope

Only artifact `11396831337`, successful source replay
`371bca3d848f5b749cf9ea989fa1fbfaca8c20cc / 37427554951 / 1`, is accepted by
`extract_native_profile_evidence.verify_provider`. Its existing four independent
packet/receipt/GL-JSONL/DX-JSONL pins remain unchanged. The capture/source base is
`8f571464be706d0abde862e124582a188f633baf / 37415102452 / 1`. The new verifier is a
separate clean, published main push to `.github/workflows/finite-warp-profile.yml`,
first attempt, in `RHS059/rust_duty`.

The original 137-entry inventory is checked for canonical safe paths, exact
file mapping, identity types and before/after equality. Exactly 128 entries are
restored: original production/build source and the existing binder's 21 inputs
(18 companions plus animation manifest/base/offset settings). The historical
example, producer, executable and logs are excluded. The historical original
pose-bridge source and compiler transcript are read only to check identities and
retained separately as evidence. Unselected assets and old executable bytes are
never read or copied.

Exactly six committed diagnostics are overlaid:

- `examples/source_visibility_geometry_probe.rs`
- `examples/source_visibility_geometry/domain.rs`
- `examples/finite_warp_probe.rs`
- `src/render/finite_warp_probe.rs`
- `src/render/mesh.rs`
- `src/render/mod.rs`

Removing the finite mesh helper and module suffix must reproduce original source
bytes exactly. The existing pose bridge is checked using the original producer's
reviewed-bridge validator. Every other production input stays byte-identical.
The helper retains all original packet/receipt/JSONL bytes and false/null flags.

The 50 visible frame IDs are the explicitly reviewed finite scope; they are not
chosen by a new coverage threshold. Every selected row must have original
positive required/possible support, no unsupported clipping and a null verdict.
The 160 empty IDs are obtained from the original source classification and must
have complete zero support. Both exact GL/DX source documents must yield the same
frame lists. This selection does not prove native fallback eligibility.

## CLI and Python API

Run from the clean verifier checkout. The caller first retrieves only exact
provider metadata, then verifies it before retrieving the single allowed
artifact through the workflow's existing artifact tool.

```
python tools/prepare_finite_probe_inputs.py verify-provider \
  --provider-metadata PROVIDER_JSON --verifier-root VERIFIER
python tools/prepare_finite_probe_inputs.py prepare \
  --provider-metadata PROVIDER_JSON --verifier-root VERIFIER \
  --packet-root DOWNLOADED/evidence/source-oracle/packet --output-dir FRESH
python tools/prepare_finite_probe_inputs.py verify \
  --provider-metadata PROVIDER_JSON --verifier-root VERIFIER \
  --packet-root DOWNLOADED/evidence/source-oracle/packet --output-dir FRESH \
  --receipt-sha256 INDEPENDENT_PREPARATION_SHA256
```

`prepare` emits `FINITE_PREPARATION_RECEIPT_SHA256=...` in its log and
`receipt_sha256=...` in `GITHUB_OUTPUT`. The caller must retain and supply that
independent value; the receipt cannot anchor itself.

Importable functions accept `Path` objects:

```
caller = caller_identity(verifier, os.environ)
anchor = prepare(packet_root, provider_path, verifier, fresh, caller)
report = verify(packet_root, provider_path, verifier, fresh, caller, anchor)
```

The importer must call `caller_identity` itself. `verify` re-reads the exact
original documents, selected original files and committed diagnostics, checks
all prepared bytes, and rejects late mutation. Call it before and after each
build/native process. The directory must be fresh for preparation. Only fresh
Cargo output under `FRESH/source/target` may subsequently grow; native results,
traces, rendered pixels, audit results and process logs belong outside `FRESH`.

## Prepared layout

```
FRESH/
  preparation-receipt.json
  visible-frames.json          # 50 IDs
  empty-frames.json            # 160 IDs
  fallback-frames.json         # sorted union of 210 IDs
  source/                     # restored production+inputs and six diagnostics
  original/
    source-packet.json
    source-receipt.json
    original-authored_viewmodel.rs
    rustc-Vv.txt
    oracle-output/frames-opengl.jsonl
    oracle-output/frames-dx12.jsonl
```

Receipt schema: `rust-duty-finite-probe-input-preparation/v1`. It contains
`caller_context`, `source_provider`, separate `capture_context` and
`source_execution_context`, `source_base_commit`, pinned `toolchain` and
`capture_rustc_sha256`, `restored_original_inventory`, `diagnostic_overlays` and
`files`. Each inventory maps relative paths to `{bytes, sha256}`. Execution and
profile flags remain false and `acceptance_verdict` remains null.

## Native caller requirements

Use `producer.execution_environment` and `producer.checked_compiler` from the
existing `build_ads_source_packet` helper. Require actual Windows AMD64 and the
original `1.99.0-x86_64-pc-windows-msvc` toolchain. The compiler transcript must
hash to `5477f9bad65b15c4c5b31fc050fc72feba651ea1b330bc75cf356a4d6b0fbc80` before
and after every build/execution; reading the retained transcript does not prove
the installed compiler identity.

Resolve Cargo from that verified toolchain. From `FRESH/source`, build each of
`source_visibility_geometry_probe` and `finite_warp_probe` exactly once with:

```
CARGO build --locked --release --no-default-features \
  --target x86_64-pc-windows-msvc --features legacy-macroquad,wgpu-runtime \
  --example EXAMPLE
```

For geometry, from the restored root, the fresh executable's argument contract
is:

```
source_visibility_geometry_probe.exe assets/animations.cfg ads-offset.cfg \
  opengl|dx12 OUTSIDE_FRESH/NEW_TRACE.jsonl ../visible-frames.json
```

Use `../empty-frames.json` separately when needed. Fresh outputs must not exist.
The finite probe's contract is:

```
finite_warp_probe.exe --native --trace OUTSIDE_FRESH/NEW_DX_TRACE.jsonl \
  --original-jsonl ../original/oracle-output/frames-dx12.jsonl \
  --source-receipt ../original/source-receipt.json --source-root . \
  --output-dir OUTSIDE_FRESH/NEW_WARP_OUTPUT
```

Retain process records using the existing `producer.process` shape
`{command, cwd, exit_code, environment}`. Separately bind the preparation anchor,
installed compiler transcript, exact finished executable hashes, actual command
arrays, contexts and output identities in the new native runner's receipt.
The preparer alone establishes neither native intermediate identity nor WARP/GL
results. Failed and incomplete calls cannot become passing execution evidence.
