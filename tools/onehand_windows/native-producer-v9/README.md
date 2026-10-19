# Windows native producer v8: bounded rigid witness reader

Source-only successor to the exact v7 package selected by PR77 head 40e31df9d46cfe4b6972fc3705489953f6aac96d. Run 39123407457 failed at native_stages.py:120 while rigid-focus read the fresh pinned rigid-frame1.json through the 2 MiB metadata default. The unchanged writer and completed rigid-frame1 stage permit at most 32 MiB. Full local vertex and polygon arrays are intentional source-side witness data; they are not per-frame duplication.

The only changed existing production line supplies 32*MIB to that rigid_frame1 read. It still calls FilePin.verify first, uses the existing strict bounded read(cap+1), rejects duplicate/nonfinite/invalid JSON and symlink/reparse paths, and compares the complete actors dictionary against independently observed target frame-1 geometry before any sampled geometry can pass. Every subsequent full float64/topology byte equality is unchanged. There is no generic role-to-cap fallback or caller-controlled cap.

The global context reader remains 2 MiB. Native writer, stage output caps, 3 GiB process RSS ceiling, initial-available and disk-floor limits remain byte-identical. This is not a claim that a JSON byte bound alone proves a process memory bound; the unchanged owned-process resource monitor remains required.

Exact Windows witness bytes were private and not uploaded. The terminal failure proves more than 2 MiB; the successful predecessor stage bounds it at 32 MiB. Historical Linux witness size 7,824,833 bytes (SHA256 935e14ca347a273851e2f275661fef41aaf905905b437934aec724ed79d27f7d) is context only, never Windows proof. Historical approved motion metadata reports rigid vertex counts 79,342, 5,584, and 5,584, but no polygon/loop counts. No exact asset-specific upper bound is claimed from incomplete topology metadata.

For finite binary64 compact JSON, a conservative 24-character scalar bound gives at most 77*N+1 bytes for an Nx3 vertex array, or 6,969,273 bytes for those three historical arrays. Topology adds at most 6*L_weapon + 5*(L_magazine+L_outgoing) + 2*(P_weapon+P_magazine+P_outgoing) + 3 bytes, plus the bounded schema/binding/actor metadata. L and P are unknown here. The independently enforced whole-file 33,554,432-byte cap, not an invented topology count, is the admission bound.

Run the CPU regression after the already pinned NumPy installation and before Blender/vendor installation:

    python -I -B run_rigid_json_regression.py --report <fresh-report.json>

It requires exactly 19 tests, zero failures/errors/skips, and verifies the entire source freeze. Actual rigid_stage and its writer/reader roundtrip a synthetic 4,552,617-byte full geometry witness through nine focus samples and a 64-sample chunk. Tests accept exactly 32 MiB, reject one byte over, retain the global 2 MiB default, and cover pin mismatch, unknown role, duplicate/nonfinite/invalid JSON, symlink, rehashed binding/geometry mutation, full sampled coordinate/topology changes, and exact one-line predecessor reconstruction.

The unchanged 23-test fragment interpreter gate remains mandatory in actual CPython 3.11.9 and 3.12.10. Its preservation assertion and three other historical assertions now reconstruct the exact v7 native_stages bytes before comparing their original hashes. None of those expected hashes was replaced or skipped. Existing 34 fragment bytes/source/AST hashes, source grid (4,240), 67 chunks, nine focused samples/four off-keys, numerical thresholds, motion, source lineage, geometry format and runtime assets are unchanged.

Local CPython 3.12.14 result: 155 tests passed (19 rigid reader, 23 fragment, 113 available predecessor regressions); 60 unavailable historical-fixture tests are listed explicitly in RESULTS.json. No actual 3.11 interpreter or Windows/native proof was run locally. Earlier AST/HOST/PROJECTION documents retained in this package describe their historical changes; RIGID_JSON_CAP_CHANGE.json and RIGID_JSON_CAP_DIFF.patch define this successor.

Adjacent readers were audited without speculative changes: full-control, source-samples, reports and conversion metadata already use explicit 32 MiB native readers; runtime evidence uses 64 MiB. The unchanged streaming assembler imposes a separate 2 MiB bound on geometry-metadata and block receipts. That later contract remains fail-closed, and its actual Windows sizes are unobserved; this rigid fix does not assert later stages will pass. Independent source-size review accompanies the publication preparation.

This package alone is not publication or native-execution admission. No Blender launch, rendering, source-to-Rust proof, game capture, activation or acceptance is claimed.
