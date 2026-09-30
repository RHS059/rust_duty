# Initial tuning contract

Status: source-informed movement plus an independently proposed rifle. No retail
fidelity claim. One reference unit = 0.0254 m is a prototype convention.

## Movement

Standing forward 4.826 m/s; sprint 7.239; side 80%; backward 70%; diagonal input
is normalized and uses the largest requested direction's ratio. Crouch 65%, prone
15%, full ADS 50% of the stance speed. Ground drive coefficient 9 (crouch12,
prone19); friction5.5 with minimum control speed2.54m/s. Air drive coefficient1,
with a105% cap relative to the greater of walk/takeoff speed.

Gravity20.32m/s²; initial jump speed6.345m/s; desired apex0.9906m. Fresh standing
jump only,500ms minimum separation. Lower-stance jump first requests standing;
release/repress to jump. Ordinary landing retains65% horizontal speed once.

Sprint: hold Shift with forward input;4-second budget;1 second/second recharge;
1-second entry budget; exhaustion requires releasing Shift. ADS,fire,lower stance
or jumping ends sprint. Weapon exit gate200ms.

Standing/crouching/prone collider heights1.778/1.27/0.762m; eye heights
1.524/1.016/0.2794m; half-width0.381m. Eye transition200ms for stand/crouch,
400ms for crouch/prone. Stand/prone routes through crouch. Expanding requires
clearance. Steps <=0.4572m are climbable, prone <=0.254m. Wedge slope limit45°.

## Kestrel-30 (all newly authored)

30-round magazine,90 reserve. 90ms cadence (~667rpm). Tactical reload credits
at1350ms, ready1950ms. Empty reload credits1800ms, ready2550ms. Tactical reload
may be canceled by eligible sprint; credited rounds stay credited exactly once.
Empty reload is uninterruptible. ADS in220ms/out160ms. Hip/ADS horizontal FOV90/65°.

Hip cone1.60° standing,1.15° crouch,0.80° prone; move addition up to1°, air1.80°.
ADS cone0.08°, move addition0.06°, air0.35°. Values are cone half-angles.
Uniform-solid-angle sampling; separate spread and recoil RNG streams. Hip bloom
adds0.35°*(1-ADS) per shot, caps2.4°, recovers4°/s after100ms.

Hip upward aim impulse0.65–0.90°, horizontal±0.30°. ADS upward0.42–0.62°,
horizontal±0.18°. Clamped to6° upward/±2° horizontal. Recovery waits120ms then
exponentially decays at21/s; it never changes player look. Visual gun kick is separate.
Hitscan samples existing recoil before applying the new impulse. Targets use34 body
and68 head damage in this slice (authored target feedback, no range falloff yet).

## Settings and measurements

Edit settings.cfg then F6, or use sensitivity/FOV keys and F5. Invalid/nonfinite
values are ignored; finite inputs are range-clamped. Reload credit is clamped no
later than ready. All units are meters,seconds,degrees except documented coefficients.

F1 exposes authoritative state; F8 records local samples at10Hz. Headless tests
use exact120Hz events. Measure objective traces before subjective tuning. Future
retail comparison requires an authorized owned installation and matched platform,
version,mode,weapon,attachments,perks,FOV,input and frame rate. A matching number
or passing test is not proof of perceptual equivalence.
