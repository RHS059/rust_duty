# Windows native producer v7: frozen-fragment AST compatibility

Source-only successor to the exact v6 package selected at PR77 commit f0d888f6003a0a582e64970075973c395a0fc3ad. The sole production-code change is a bounded serializer inside pinned_code.py. It accepts CPython 3.11 and 3.12, checks the exact 73 AST node kinds and field layouts used by the 34 existing fragments, and supplies the absent empty type_params field for FunctionDef/ClassDef on a disposable 3.11 serialization copy. The executable AST is never changed. Every original fragment source byte, source hash, AST hash, original-file hash and existing relocation check is retained.

Candidate 39120010389 failed control-export at the original fragment-AST assertion. The first frozen record is GeometryBytes. Its 3.12 dump includes three empty type_params fields that the upstream 3.11 schema lacks. This source/schema diagnosis is not an actual 3.11 parser receipt: local testing used CPython 3.12.14; actual 3.11.9 and 3.12.10 regressions must run before native installation in the successor workflow.

Run the stdlib-only compatibility gate with each real interpreter:

    python -I -B run_fragment_compatibility.py --report <fresh-report.json>

The gate verifies the source freeze, requires exactly 23 tests with zero failures/errors/skips, and requires all 34 unchanged AST hashes. Its report includes actual interpreter identity and each unmodified runtime AST hash separately from the audited serialization hash. The 3.11 schema projection test is explicitly labeled simulated when run on 3.12.

136 available source-only tests passed locally; 60 historical-fixture omissions are listed in RESULTS.json. The 23 focused tests cover original source/hash/body preservation, all 34 compilations, exactly the three historical relocations, unsupported runtime/syntax/layout rejection, missing/extra/nonempty fields, scalar/annotation/decorator/parameter mutation, and no mutation of executable trees. Existing preservation assertions reconstruct the exact v6 pinned_code bytes by removing only the marked serializer block and reverting its one call-site change.

All other production Python files, native host/process ownership, exact 4240 sampling, off-key and numerical thresholds, geometry/frame packing, memory bounds, context and source lineage are byte-identical to v6. Consumer math fingerprints remain in the existing pinned 3.12 controller role. No native execution, source-to-Rust proof, rendering, game capture, activation or acceptance is claimed.
