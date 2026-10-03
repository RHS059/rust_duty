# Current reload WIP: authored Blender → FBX → runtime

The canonical source is selected by SHA-256, and the source Action and requested
range are explicit. Stored Action key extents are never interpreted as approval.
The current full tactical delivery is `RD_Reload_Tactical_HandApproach_AndReturn_WIP`,
native frames 0–156 (Blender frames 1–157), at 60000/1001 fps. Its reviewed
range is 48–156; the earlier prefix remains WIP. The separate current
`RD_Reload_Tactical_Hands_Opening_WIP` owns reviewed native 0–30. The former
preserves an authored base-to-48 prefix for some left channels; it does not contain
the latter opening motion. The canonical guarded base is exported as a static
reset. No empty-reload, ADS or fire Action exists in this source. It is evaluated directly as a single existing Action, not joined from
two reviewed segments. Current source motion, including imperfect poses, stays intact.

`tools/export_reload_wip_fbx.py` produces an FBX, immutable evaluated full-skin
and rigid-prop witnesses, and a source/action/curve-hash manifest. It selects the
named Action and mutes NLA, exports only arms and the three rigid actors, and
never saves or edits the canonical `.blend`.

`tools/import_fbx_viewmodel.py` imports that FBX in a fresh Blender 4.3.2 scene.
Two audited, in-memory importer patches preserve fractional-rate timing and dense
keys. Installed Blender files are unchanged; unfamiliar versions/signatures fail.
A static GLB transports geometry only. FBX evaluation is the animation authority.
Packed materials can be restored from the exact hash-verified source `.blend`;
this copies materials only and does not import animation from it.

The importer verifies the existing canonical 72-bone name/parent closure and
rejects positively weighted omitted bones. It removes only unweighted helper
bones outside that closure for static geometry export, verifies rest matrices,
and preserves up to eight weights (the supplied skin needs six). It does not
raise the 128-bone cap or silently discard deforming parents.

## Timing and visibility

The chosen rational policy samples every 1/64 native frame, plus explicit
111.98 and 112 switch landmarks and their ±1/65536-frame neighbors. Every chosen
time must remain distinct after float32 serialization; collisions fail instead
of deduplicating keys. This is a finite resampling policy, not an assertion of
continuous equality at arbitrary real times. Independent witnesses include
integer/quarter/off-grid times and tight switch neighborhoods.

FBX all-zero scale marks an invisible rigid actor. It becomes invisible STEP
visibility with a nonrendered identity-transform placeholder; partial singular
scales fail. The actual visible transforms are preserved. Verification checks
both visible and invisible masks, never treats the placeholder as a visible pose.

## Proof and scope

`tools/verify_fbx_segment.py` compares the actual Rust CPU sampler's complete skin
and visible prop transforms to immutable Blender witnesses. The vertex map is
fixed at the first pose, checked bidirectionally, and retained for every sample.
Without `--sampler`, its output is explicitly a Python diagnostic, not runtime
verification. The predeclared position limit is 1 mm; measured maxima are reported.

The original reviewed segments passed Rust sampling at 425 and 889 independent
witness times: maximum skin errors 0.0775 mm and 0.0540 mm, respectively, with no
visibility mismatches. These measurements do not approve the missing interval,
full-clip appearance, gameplay camera, materials, or interaction behavior.

The canonical source and the complete game remain in the repository/build flow.
Large FBX/GLB/oracle files are temporary pipeline intermediates; runtime companions
and provenance are the generated deliverables. No source pose is reconstructed
in game code, and no export quality gate is used to hide current WIP motion.
