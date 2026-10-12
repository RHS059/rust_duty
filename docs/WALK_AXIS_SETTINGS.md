# Walking translation and focus handling

The pause menu has three independent walking translation sliders for the selected
weapon: X sideways, Y vertical and Z depth in the runtime viewmodel basis.
Each value ranges from -1 to +1 and its gain is `1 + value`: -1 removes that
axis's walking displacement, 0 keeps the current motion, and +1 doubles it.
Reset restores all three values for this weapon only.

Absolute viewmodel X (Left/Right), Y (Up/Down), and Z (Depth) sliders sit above the
walking controls, each with a +/-0.20 m range. Positive Z moves toward the camera.
Arrow keys nudge X/Y; Page Up/Down nudges Z. They change
hip placement for the whole viewmodel; walking XYZ changes only animated displacement.
Saved placement fades out with the visible ADS transition, reaches zero at full
aim, and returns on exit. Interrupted aim reversals continue from the current
placement. The authored route uses native ADS progress and the shared run blend,
so gameplay readiness cannot center the weapon prematurely. Saved slider values
are retained while aiming; walking controls keep their independent behavior.
Moving either kind of slider saves the combined settings file on release, and
F5 remains available for arrow-key changes. Reset Walking never resets placement; Reset Position clears only absolute X/Y/Z.
Older settings files without viewmodel_z load it as zero.

Tab/Shift+Tab select the buttons and six sliders; Up/Down move selection.
Left/Right adjust the selected slider and Home/End choose its bounds. Enter/Space
activate the selected button without also resuming. With no selection, the
existing placement nudge keys still work. Save / retry and F5 retry persistence.
Save failures remain visible until a successful save or explicit F6 discard/reload;
unrelated notices and closing/reopening the menu cannot turn failure into success.
A failed F6 read retains the current values.

The settings use stable IDs (`hk416a5` for the current authored rifle and
`kestrel30` for the procedural fallback), not display labels, clip revisions or
paths. `--weapon-id=ID` binds another weapon to its own entry. IDs contain only
ASCII letters, digits, underscores and hyphens. The selected settings file stores
`walk_translation.ID.x`, `.y`, and `.z`; missing values default to zero, finite
values clamp to the slider range, and nonfinite values are ignored. Releasing a
slider or resetting saves automatically. F5/F6 still save/reload this same file;
`--settings=PATH` retains its existing meaning. Save failures are shown in-menu.
The update system retains this user settings file across game updates.

Only the walking layer's displacement from the current unwalked hip/ADS pose is
scaled. Absolute weapon placement, rotation and timing are retained. The actor
and every evaluated arm/hand transform receive the same rigid translation, so
weapon-relative contact is preserved. The source `righthand_prop` and bound
`hk416_weapon` actor share their origin (read-only inspection of the pinned r5
source puts their difference below 0.0000001 m). Scaling happens before sprint
composition; reload has its separate unchanged route. Idle/fire/jump/sprint
animation data and gameplay are unchanged. The procedural fallback has only a
vertical walking bob, so its X/Z displacement remains zero at every setting.

Click the explicit Resume/Enter the Range button, or press Enter/Escape, to play.
Dragging sliders or clicking Reset cannot resume or fire. Interrupted drags save
on the interruption and release their pointer ownership.

On Windows, foreground-window ownership is sampled each rendered frame. Focus
loss pauses, releases cursor confinement and shows the cursor; returning leaves
the game paused. The refocus frame discards button input. Gameplay and updater UI
share a resettable input event subscriber, so missing release events or later key
repeats cannot restore stuck movement/fire. Cursor ownership changes only on game
capture transitions, avoiding repeated global ungrabs while another app is active.
Explicit capture jobs ignore physical focus/session input and never confine the
cursor. A complete focus-loss-and-return between rendered frames cannot be
observed by this snapshot. Other platforms retain the Alt/Super shortcut fallback;
this change does not claim native focus-event coverage there.

Tests cover independent axis gains, neutral-relative displacement at partial/full
ADS and walk weights, weapon-relative transforms, unchanged idle/reload/full-run
outputs, persistence and invalid input, interrupted UI dragging, reset isolation,
focus/refocus with missing releases, and repeated focus/resume boundaries.
Native Linux pause-menu interactions and saved values were inspected; native
Windows Alt-Tab behavior still needs runtime verification beyond Windows CI.
