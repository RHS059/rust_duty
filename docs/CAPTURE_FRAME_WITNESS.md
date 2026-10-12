# Validation-only capture frame witnesses

Ordinary captures do not contain a witness. Automated callers can opt in with
`--capture-frame-witness=<64-lowercase-hex-identity>`. The game records an opaque
64×22 pixel code in the captured target's top-left corner through the normal
ordered draw list immediately before readback. It is not a postprocessed PNG
overlay. The original camera is restored, and no simulation, input, pose, or
asset data changes.

The independently expected identity is SHA256 of compact, sorted-key UTF-8 JSON
with exactly `source_commit`, `exe_sha256`, `run_id`, `run_attempt`, `scenario`,
and `backend`. Native orchestration must derive those fields from its verified
source/build/run/scenario chain, never from the PNG or declared witness alone.
The renderer receives that identity as a validation argument. Each capture also
encodes its zero-based sequence frame index and bitwise complement. The primary
sidecar's `frame_witness` contains schema `rust-duty-capture-frame-witness/v1`,
`frame_index`, and `capture_identity`; gameplay/time sidecars are unchanged.

The physical wire format is fixed:

- Top two rows: 32 red pixels followed by 32 blue pixels.
- Remaining ten rows of cells: 32 columns, each cell 2×2 pixels.
- Payload: little-endian u32 frame index, its u32 complement, then the 32 identity
  bytes. Bits are emitted least-significant-first within each byte.
- Zero cells are opaque black; one cells are opaque white.

`tools/verify_capture_frame_witness.py` independently decodes every marker pixel.
Its `verify` API requires the expected frame index and invocation identity as
explicit arguments, checks the exact sidecar schema, and rejects stale/swapped
frames, old captures with the same index, rewritten metadata, broken headers,
bit errors, invalid complement, non-RGBA8 images, and transparent pixels.

Historical unmarked images can still be read as historical diagnostics. They do
not acquire a frame-binding claim. Current native acceptance must require the
independently derived identity on every relevant sequence frame and recheck it
when aggregating artifacts. A declared marker is always decoded even in the
historical-reader compatibility path.

Because the identity includes the backend and scenario, those identity bytes
are deliberately excluded from cross-backend primary-sidecar equality after
independent validation. Witness schema and frame index remain exact. The
ADS-versus-placement-offset visual comparison excludes only the validated
64×22 marker rectangle and compares all remaining pixels exactly. Normal
unmarked captures keep the original PNG-byte comparison. Invalid or mixed
marked/unmarked inputs cannot request this exclusion.

CPU decoder/producer tests are not native execution evidence. This witness
protects frame readback and artifact binding; it cannot certify a malicious
producer's scene semantics, exact sight landmark coordinates, human visual
approval, native pointer behavior, or GPU performance. Native orchestration and
fresh passing executions are required before claiming the binding gate closed.
