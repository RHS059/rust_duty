# Windows game continuation v4: exact hash-domain repair

This source-only successor derives from the frozen audio-preserving game
continuation v3. It repairs two protocol-boundary comparisons without changing
the producer protocols or accepting weaker evidence:

- The expected owned-process HostBinding environment hash uses the unchanged
  process adapter's canonical-JSON-plus-newline digest. Controller command
  contexts and returned environment hashes keep the controller's existing
  no-newline semantic digest.
- The candidate runtime-context file reference must equal the actual context
  path and serialized-file SHA256. The runtime binding and high receipt still
  carry the unchanged semantic context digest. These identities are deliberately
  distinct; neither hash substitutes for the other.

The continuation pins orchestration v6 and exports through the versioned v4
preflight path. Only these boundary fixes, the orchestration pin, the preflight
prefix, focused tests and this documentation differ from v3. The original 58
test methods are retained. Their same-candidate fixture now writes actual
canonical JSON with a newline and independently computes its semantic digest;
new regressions reject wrong domains, changed bytes and foreign same-byte paths.
The additional test_game_command_contract.py suite uses the real frozen adapter
HostBinding, Limits and producer exact-comparison routine with a deliberately
synthetic nonexecuted process fixture. It checks positive and mutated receipts,
preserved controller hashes, environment override, and the 600-second capture
deadline. No test result here is actual Windows process or animation evidence.

The exact game features remain audio,legacy-macroquad,wgpu-runtime. Every byte
of build_game.py, game_plan.py, game_source.py, run_continuation.py and
verify_dx12.py is retained. Locked dependencies, audio provenance assertions,
sampler feature isolation, full source/vendor closure and compiler/linker/SDK
checks remain mandatory. The measured source inventory remains 957 rows and
265961235 bytes at dd1d2cb4bae6e0b2d2509edfc8e8c301184cf4f4. All publication
paths are tools/onehand_windows paths excluded by the unchanged source selector.

All native full-4240/67 and focus gates, motion, same-candidate receipt checks,
30/60 Hz DX12 checks, capture-before-delivery order and public inactive defaults
remain unchanged. This package supplies no independent acceptance or enabled
admission. Immutable source commits, genuine independent review, resolved
manifests and final admission are separate publication steps. The active
workflow is composed only after both package pins are frozen, outside those
packages, avoiding a self-referential hash cycle. Frozen predecessors and prior
receipts are untouched. Actual Windows build, full proof, audio-enabled game
capture and delivery are still required before the game work is complete.
