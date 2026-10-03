# Canonical current reload source

`current.blend` is the authoritative editable source for the current full two-hand
reload WIP. It is committed as ordinary Git data (not Git LFS or an external link).
`source.json` freezes its SHA-256, exact Action, requested native range and timing.
The initial file is exactly 8,247,987 bytes, SHA-256
`8cec36c6bfcc4967cb80629b40ecdced3c0b5507914aec7eb3d2d614f2d758fd`.

The full native 0–156 range is deliberately exported as WIP. Only its native 48–156 range has prior review; the authored prefix 0–48
remains WIP. The separate current Opening Action is reviewed over 0–30. Exporting it
does not approve the gap, hand contacts, or complete motion. No clips are joined.
Other stored Actions are retained in the file and inventoried with curve hashes in
every export manifest. The primary selected Action alone drives the tactical slot. The distinct Opening
Action (0–30), guarded reset (0) and pickup inspection pose (54) are independently
exported, verified and packaged under `assets/reload/alternates`; they are not
stitched into the tactical animation or mislabeled as complete gameplay slots.

To change the animation, edit this file in Blender 4.3.2 and update the SHA-256 and
byte count in `source.json`; change its action/range only deliberately. Commit both.
Every PR and supported branch push runs the asset-export job before game builds.
Any source/hash mismatch, exporter/converter failure or Rust sampler parity failure
blocks the Windows and Linux playable artifacts. Source auto-execution stays off.

The committed 43 locomotion clips remain in `assets/locomotion`. Generated reload
companions are downloaded from this same workflow run, then packaged alongside the
game EXE, settings and notices. No Library or other external asset store is needed.
