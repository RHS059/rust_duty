# Windows native producer v5: exact Windows addon-profile selection

Source-only successor from immutable PR77 commit 01e3d821d197799a342b7738b84e835b11197f24 native-producer-v4. The only production change is pinned_code.py's exact context-v3 dependency and version diagnostic. All native math, stages, patch receipts, loaded-function hashes, process admission and original source fragments remain byte-identical. Original Linux context/profile and all predecessors are preserved.

The context successor binds verified official Windows raw addon bytes separately from unchanged loaded-source function receipt hashes. No normalization fallback is introduced. New portable dependency tests reject changed context manifest/profile/code and verify exact predecessor production hashes. Historical baseline test files remain preserved; any unavailable local-only fixtures are disclosed in RESULTS.json rather than fabricated.

Independent acceptance and actual Windows native/source-to-Rust proof remain pending. No publication, native process, render or Rust build was performed.
