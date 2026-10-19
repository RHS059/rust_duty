# Pending native invocation contract

The following is an execution contract, not evidence that these commands ran.

1. Independently review this consumer-v5 and selected producer-v4/context-v2 privacy-projection closure together with the upstream workflow/controller. SELECTED_PRODUCER_PINS_SHA is an exact source selection, not independent acceptance. Historical predecessor producer-v3 review is retained separately; preserve exact transport-v2 correction review and actual Windows smoke pins. Do not edit frozen dependencies.
2. Materialize already-authorized source/control inputs and same-target native export, source/FBX focus, rigid frame1/focus/chunks, geometry and all 12 packed blocks. Native references use `admission.py::verify_stage(stage_context_path, context_sha256, context_package, receipt_sha256, terminal_sha256)` and `verify_gate(path, expected_sha, context_package)` from the pinned selected producer-v4 package after independent acceptance. Its host manifest uses `rust-duty-windows-native-host/v2`, including exact native environment digest and key inventory.
3. Obtain actual Windows locked/offline Rust build evidence. `rust-duty-windows-rust-build/v1` fields are exact in `runtime_context.verify_build`; source files include every ordinary file in every subtree, including nested `target` and `.git`, and every dependency package manifest and target source path must be an actual member of exactly one pinned inventory. No six-file probe-only closure is accepted. The actual leaf executable must be `sample_viewmodel_clip` built for `x86_64-pc-windows-msvc` and match the fresh PE hash.
4. Assemble the candidate using the unchanged full `StreamContract` API under the separately reviewed caller. Preserve native bytes and all reports. The runtime consumer independently checks those existing bytes; it does not assemble, build or fetch them.
5. Write a caller-pinned `rust-duty-windows-runtime-assembly-inputs/v1` JSON with exact fields: schema, binding (native candidate binding), conversion_gate ({path,sha256}), assembly_report ({path,sha256,bytes}), geometry ({path,sha256,bytes}), blocks (12 ordered receipt records). The conversion gate must verify all 13 real native stages. The assembly report is the exact unchanged assembler's report.
6. Write `runtime/manifest.json` with exact schema `rust-duty-windows-runtime-manifest/v1`, binding, assembly_gate_sha256, files ({vra,vrs,vrm} role pins), timing_policy (original explicit-rational-resampling/256/24321/collision-reject/switches-empty policy), runtime_parity_verified:false, activation_authorized:false. This new manifest never uses the old approved-source diagnostic schema.
7. Create the immutable `rust-duty-windows-runtime-context/v1` context under candidate `contexts/`. Exact role sets and fields are in RuntimeContext.validate. Protected roles include baseline/original_delta/canonical/source_grid/reference witnesses, sampler, transport_review, actual transport_smoke audit, and transport_smoke_summary. Every native/source/runtime asset/evidence role belongs to the same candidate. roots include audited_source (original read-only workspace code tree), context_package (frozen v2), native_producer, process_adapter, source_package, reference, rust_source. Dependencies include context/consumer/producer/transport PINS and canonical runtime_environment_sha256. The environment file contains explicit values and is passed directly to OwnedProcess, with only keys and digest recorded in process receipts.
8. Input bundles use schema `rust-duty-windows-runtime-inputs/v1`, binding (full RuntimeContext.runtime_binding), kind, index and stages. A stage reference has exactly context, native_receipt, process_terminal; each is {path,sha256}. Initialize stages are source=export and rigid=rigid-frame1. Focus stages are source=source-focus, fbx=focus-import, rigid=rigid-focus. Chunk stages are source=source-chunk, fbx=chunk-import, rigid=rigid-chunk, all same chunk index. Focus and initialize index are null.

Common CLI prefix, with actual explicit target paths and hashes:

    python -B consumer.py --context CONTEXT --context-sha256 SHA256 --context-package FROZEN_CONTEXT_DIR --environment ENV_JSON

Commands in order:

    loading
    initialize --inputs INIT_INPUTS --inputs-sha256 INIT_SHA
    focus --inputs FOCUS_INPUTS --inputs-sha256 FOCUS_SHA
    chunk --index 0 --inputs CHUNK0_INPUTS --inputs-sha256 CHUNK0_SHA
    ... exact ordered chunks 1 through 66 ...
    aggregate

Stages preserve `.started.json`, successful `.json`, or `.failed.json`. Failed attempts require a reviewed fresh revision/attempt identity, never overwriting evidence. `OwnedProcess` captures durable native attempt/start/transport/terminal/stream/sample evidence separately. No CLI accepts reduced geometry counts, partial grids or synthetic transports.

Optional retirement after independent successful consumption:

    ...common prefix... retirement-plan --index N

The result defaults to a nonmutating plan. Only after separately obtaining required user authorization for the exact plan hash may the coordinator invoke:

    python -B retirement.py --context CONTEXT --context-sha256 SHA256 --context-package FROZEN_CONTEXT_DIR --environment ENV_JSON --verified-plan PLAN --plan-sha256 PLAN_SHA --authorization-ref VERIFIED_USER_APPROVAL_REFERENCE --execute-authorized

This explicit executor acquires the exclusive session lock, rechecks the plan and independently reconsumes raw evidence before deleting only the exact successful raw source row/skin files. It never runs as part of initialization, focus, chunk or aggregate. Failures and partial retirement remain blocked for inspection.

Reserve 300 minutes runtime execution within the reviewed 330-minute job envelope; stage timeout stays 1,800 seconds. Production, Rust proof and later GL/DX12 captures remain distinct. No animation-equivalence, rendered appearance, gameplay, artistic acceptance or game activation follows from transport smoke, schema tests, assembly, endpoint load or focus alone.

## Complete build-input closure

`target_directory` is absolute and disjoint from every source/dependency snapshot. The exact Cargo argv adds `--message-format=json --target-dir TARGET`; build output must not be hidden by source-inventory exclusions. The supervised build-process receipt includes `cwd` equal to the source root, `target_directory`, and `target_empty_before_build:true`, alongside its existing command/host/environment/input-closure/exit/stream records. The controller must actually check emptiness before launch, preserve the snapshots and supervise the whole Cargo build. These facts are externally trusted process evidence, not claims inferred from self-hashes.

`compiler_inputs` is a {path,sha256,bytes} record for this exact JSON:

    {schema: "rust-duty-rust-compiler-input-closure/v1",
     command_sha256, source_tree_sha256, dependency_closure_sha256,
     cargo_messages: EXACT_BUILD_PROCESS_STDOUT_RECORD,
     invocations: [{artifact_sha256: DIGEST_OF_CARGO_COMPILER_ARTIFACT_JSON,
                    dep_info: RETAINED_RUSTC_DEP_INFO_RECORD,
                    generated_inputs: [{file: RECORD, producer: RECORD}]}]}

Every Cargo compiler-artifact requires its actual retained dep-info; dependency paths must include the crate root and resolve to current pinned source/dependency inventory members or explicitly pinned generated inputs. Cargo stdout must finish successfully and identify the actual sampler as an executable output. Dep-info is parsed as bounded data, never shell-expanded. Absolute Windows drive paths and escaped whitespace are supported. Relative input paths are resolved from the captured source-root build cwd. Missing dep-info or an unrecognized path is a blocker, never silently skipped.

Each generated-input producer record has exact fields:

    {schema: "rust-duty-cargo-generated-inputs/v1",
     build_process: EXACT_SUPERVISED_CARGO_BUILD_RECORD,
     source_tree_sha256, dependency_closure_sha256,
     out_dir: ACTUAL_CARGO_BUILD_SCRIPT_EXECUTED_OUT_DIR,
     outputs: [GENERATED_FILE_RECORDS]}

The whole supervised Cargo process is the recorded producer. No inner build-script command or inner stdout is invented. Every generated input must lie beneath an OUT_DIR observed in the exact Cargo JSON stream, have the current output hash/length, and be referenced by actual dep-info. The workflow's build-closure creation helper can construct this evidence after the real authorized build; this package only verifies it.

## Retained raw evidence

The fixed plan path is `runtime-proof/retirement-plan-NNN.json`. Its started receipt, complete schema/flags, original chunk hash, exact ordered raw list and exact preserved list are verified before deletion and during later aggregate admission. The preserved list starts with the original `chunk-NNN.json` record, followed by inputs, source index, session, focus and sampler terminal. The journal is fixed at `runtime-proof/retirement/chunk-NNN.plan.json`; its plan record, authorization trace, index, chunk hash and exact raw list must match the successful retirement receipt. A changed current chunk cannot be repaired by replacing only the later retirement receipt. Any failed marker or partial raw presence blocks admission.

After that independent retained-plan check, source-chunk admission calls `verify_retained_stage(..., retired_files={POSIX_RELATIVE_NAME:{sha256,bytes}})` in the reviewed producer. The full descriptor row+skin inventory is the only permitted absence. All other native envelope, stage/index, context, process/resource and output checks are shared with ordinary `verify_stage`. Input bundles always require the exact nonempty source/fbx/rigid roles; no empty or wrong-kind bundle is accepted.

## Exact-byte materialization

This package's `.gitattributes` uses `* -text`, covering every new pinned input, including its own attributes and PINS. The local fixture exercises real Git index/checkout with `core.autocrlf=true` and `core.eol=crlf`, then checks every package file byte-for-byte. It is a CPU/local-checkout fixture, not an actual Windows execution.

The package-level rule does not change frozen sibling packages, original audited source, reference witnesses, or Rust dependency snapshots. Every external role must be materialized through an already-authorized hash-preserving archive/blob transfer, or a separately controlled checkout whose own attributes preserve exact bytes before indexing/checkout. Recompute all required pins before any native stage. Default Windows text-converting checkout of uncovered roles is not an accepted route. Do not edit a frozen dependency to repair transformed bytes or replace its pin with a new local hash.

## Actual Rust process verification in v3

`transport.verify` requires the externally pinned terminal SHA on every call and invokes the byte-identical producer-v4 strict process reader. Its exact expectations include the runtime context/build/host/environment/session lock, sampler command and cwd, limits, row count, supervisor identity/size and leaf sampler identity/size. Runtime process records now include derived `retained_process_validation` alongside the unchanged terminal fields. This is a runtime receipt field, not a change to the OwnedProcess terminal schema. Existing consumer APIs rederive and compare it automatically. No CLI/context/input-bundle change is required.

The whole-Cargo producer and workflow source remain separately reviewable. A reviewed source dependency is never a successful real build, source-to-runtime proof, complete-grid pass or authorization for native execution.
