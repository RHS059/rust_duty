# Payload-only native inventory boundary

The published N8 controller required at least one standalone native output. Its rigid-focus and rigid-chunk producers intentionally carry their full rigid witness in receipt payload and write no standalone output. Run 39126616057 stopped after successful rigid-focus child completion at the static admission error `bounded output inventory`.

N9 admits exact empty output_files only for the already context- and receipt-bound rigid-focus or rigid-chunk role. Other roles still require 1..150 entries. It still rejects any unexpected on-disk file, excluding only the root receipt.json; a nested receipt.json is not excluded. Existing file hashes, byte caps, context/host/process checks, full payload checks and numerical fragments are unchanged.

New CPU regressions exercise native_entry.main output enumeration and receipt construction followed by verify_stage with real StageContext schema/hash and envelope hash binding. Synthetic Windows host/process and Blender/source preconditions do not establish native provenance or numerical proof. Both payload-only roles, final chunk, tampering, missing data, wrong roles and all 67 chunk indices are covered.

Historical test assertions reconstruct the exact prior admission bytes for predecessor-preservation checks; no predecessor source is modified. The final package needs reviewed dependency rebinding before any production execution. No native process, publication, activation or game capture was performed here.
