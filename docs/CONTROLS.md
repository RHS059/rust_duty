# Press-to-toggle controls

The default controls are:

| Input | Behavior |
| --- | --- |
| Right mouse | Press to enter ADS; release keeps ADS; press again to leave ADS |
| Left Ctrl or C | Press to crouch; press again to request standing |
| Z | Press to go prone; press again to request standing |
| Space | From a lower stance, request standing and clear that stance toggle; from standing, jump |
| Left Shift | Hold sprint; a new press cancels toggled ADS |
| Left mouse | Hold automatic fire, unchanged |

Crouch and prone are one exclusive desired stance. Pressing Z while crouched
requests prone, and pressing Ctrl/C while prone requests crouch. If both stance
actions are pressed in one render frame, prone wins. Ctrl and C are aliases for
one action: release both before pressing that action again.

Stance inputs express a desired state, not an immediate camera/body change.
Existing simulation clearance checks and eased transitions still apply. Leaving
prone passes through crouch. If a ceiling prevents standing, the standing request
remains active and finishes once there is room. Space does not launch the player
from a lower stance; press it again after standing to jump.

A new Shift press cancels toggle ADS even if movement does not qualify for sprint.
Pressing right mouse while Shift remains held can enter ADS and stop sprinting.
Jumping retains ADS intent. Reload temporarily suppresses ADS through the existing
simulation rules; the weapon returns to ADS afterward if its toggle is still on.

## Optional hold controls

Use `cargo run --locked --release -- --hold-controls`, or run the packaged executable
with `--hold-controls`, to use the original hold-to-ADS/crouch/prone mode. The pause
screen shows the selected mode. This launch option applies to either gameplay
profile and does not modify tuning presets. Hold mode retains the original ADS
priority over sprint and the simulation's Space-to-stand override.

## Reset and focus safety

Pause, resume, F2 reset, and the existing detected focus-switch/long-frame pause
clear desired ADS and stance state along with pending fire/jump/reload work. A
control held across that boundary must be released before it can reactivate.
Resume clicks never fire. Standing after resume remains subject to headroom.

Focus detection remains limited to the existing Alt/Super shortcut and >250 ms
frame-hitch checks. Use Escape before switching applications.

## Input and verification

`src/control.rs` contains a pure `ControlState`, separate from the existing
`IntentLatch`. Physical input is sampled once per render frame. Desired toggle
state persists through frames with no simulation step, and reading it during
multiple fixed steps never flips it again. Held buttons, including repeated key
press flags, cannot repeatedly toggle. Space clears stance desire when its
latched jump request is consumed at a fixed step, so it cannot return next tick.

`tests/toggle_controls.rs` covers toggle/release/repress, held-input repeat,
zero/multiple-step frames, exclusive stance switching, simultaneous-key priority,
reset/resume rearming, hold-mode behavior, sprint/ADS interaction, jump-to-stand,
headroom, eased prone transitions, reload/ADS eligibility, and fire-latch safety.

Manual runtime checks:

1. Tap right mouse, release it, and look/move: ADS remains on; a second tap exits
2. Tap C twice, then Z twice: each enters its stance and then requests standing
3. Switch C → Z → C: crouch/prone requests are exclusive and smoothly animated
4. From either lower stance, tap Space: stand, stay standing, then Space again jumps
5. Request standing under a low ceiling: remain safely lower until there is room
6. Toggle ADS, then tap Shift: ADS exits; tap right mouse with Shift held to aim
7. Pause/resume, F2 reset, and trigger the supported focus-pause path while holding
   a control: there is no reactivation until release and a new press
8. Launch with `--hold-controls`: ADS/crouch/prone end on release; labels say Hold
