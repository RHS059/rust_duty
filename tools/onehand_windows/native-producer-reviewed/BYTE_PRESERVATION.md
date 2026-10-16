# Required exact-byte dependency checkout

This is a pending orchestration admission prerequisite, not an executed checkout claim.

The package-local `.gitattributes` contains `* -text`. It does not cover sibling paths. The current repository root does not protect this entire imported dependency closure. A Windows user/global `core.autocrlf=true` can therefore alter pinned Python, JSON and Markdown bytes before their use.

The reviewed workflow must use an authorized, byte-preserving fresh checkout or exact-blob extraction route. A global/user `core.autocrlf=true` setting must be included in the route test. An explicit workflow checkout override applied before checkout, or source-only attributes covering every dependency before a fresh checkout, may protect bytes; changing configuration after files were already checked out is insufficient. Exact-blob extraction must also reject attribute/filter substitutions, unsafe paths, symlinks and unknown files. Do not rewrite existing dependencies, historical receipts or expected SHA256 values to make altered bytes pass.

Required closure, verified after materialization and before native launch:

- Current producer ALLOWLIST/PINS and BOUNDARY_ADAPTATIONS manifest.
- Candidate-context-v1 complete PINS closure (`cee1e6fc...c9d378`).
- Exact reviewed process-adapter-v2 complete closure, review acceptance and actual Windows smoke audit/summary/retained process evidence.
- Authored source-package PINS, baseline/delta identity, hash-only reference package and all 34 approved/regenerated reference witnesses.
- All original files enumerated in AUDITED_FRAGMENTS.json, including the source-selection/sample/restoration code, dense_backend/window_import and safe format/geometry/packing modules.
- The original 4,240-time grid and existing canonical repository input assets/locomotion/asset.vra, verified by their existing hashes.
- The separately inspected official Windows Blender/Python binary, DLL, FBX addon and glTF source closures. These use their inspected vendor identities, not line-ending heuristics.

StageContext.verify_files, verify_package, host_build and verify_transport must all succeed on actual materialized inputs. Their failures block the stage; neither a plan nor source review bypasses them. The orchestrator must retain hash-only before/after checkout inventories and the effective checkout commands/configuration. A controlled one-byte/CRLF mutation should fail pin admission in the workflow's source-only test.

No private BLEND, FBX, source rows or geometry is added to this source package or given a new upload route. New runner-local generated/control outputs acquire their own actual hashes; they are never expected to match historical Linux bytes.
