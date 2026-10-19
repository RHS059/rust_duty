# Portable source-test coverage map

The public tests preserve the behavior and negative mutations from their
original source-only preparation suites. `tools/combined_source_contracts.json`
contains only original-source fingerprints and immutable baseline identities.
It contains no production geometry or native pass receipt.

| Existing assertion | Repository-portable equivalent |
| --- | --- |
| App pause/reset/clock blocks equal replay baseline | Exact SHA256 of each same block, independently compared to published parent 71857605 during preparation |
| All FocusInput initializers complete; reversing E0063 repair fails | Same initializer inventory and negative mutation; unrepaired whole-source SHA pinned to original v4 source |
| Motion files absent from overlay | Exact current-head hashes of high-mantle source, default manifest, input frame and session; removing only two telemetry accessors and accepted-observer call restores published simulation SHA |
| App-edge renderer additions can be removed to recover replay source | Same exact remove-only comparison, then undo preserved CI-only guards; SHA must equal independent replay-v3 renderer source |
| Exact renderer status/source/manifest and Rust guards | Actual repository renderer bytes plus immutable historical source/manifest identities and original string/guard checks; an added test proves historical native admission rejects this different source |
| Startup only adds validated menu argument/predicate | Reverse those exact changes and compare independently pinned pre-startup app/menu/production-input hashes |
| Startup Rust regression matrix | Same valid/invalid case inventory, ordinary-menu checks, all required flags, mixed-mode rejections and original Rust test names |
| Startup missing typed route/blanket bypass negative mutations | Same four mutations and required rejection |
| Complete production menu callsite inventory | Same repository-wide Rust source scan and exactly one production callsite |
| Startup patch reproduces exactly three reviewed files | Exact byte hashes of the same three reviewed source files |
| Synthetic trace, receipt, warning/error, file/output and resource tests | Existing positive/negative tests unchanged; repository-relative helper lookup only |

No test is removed or newly skipped. The combined capture suite retains its
pre-existing explicit requirement for `COMBINED_SOURCE_FREE_TEST_TRACE` for
Rust-to-Python route comparison and full synthetic traces. When that trace is
provided, every test runs; without it the original explicit skips remain.
This trace is source-free CPU evidence, not a native asset or rendered capture.

The frozen native source and manifest pin constants and every runtime, source,
image, process and resource threshold remain unchanged. The public source's
extra CI-only guards intentionally prevent borrowing the old native receipts.
