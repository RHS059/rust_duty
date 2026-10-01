# Weapon-relative hand IK authoring fixture

`tools/create_weapon_ik_rig.py` creates a complete original Blender scene that makes the weapon attachment layer inspectable. It contains a moving dummy prop, two synthetic arm chains, actual named weapon target bones, keyed base arm motion, independent grip-influence drivers, and evaluated transform checks. No external weapon, arm mesh, texture, or animation is read.

The runtime counterpart is `src/weapon_ik.rs`. Both use the same target names and default wrist calibration. The fixture demonstrates the attachment contract; it is not a replacement for the runtime arm solver or a calibration of finger contact against a particular mesh.

## Generate and check

From the repository root, using Blender 4.3 (validated with 4.3.2):

```sh
blender -b -t 4 --python-exit-code 1 --python tools/create_weapon_ik_rig.py -- --render
```

The helper creates `fixtures/weapon_ik/weapon_ik_demo.blend`, three preview PNGs, calibration and hierarchy JSON, and `validation.json`. A successful run prints `WEAPON_IK_FIXTURE_PASS`. The `--python-exit-code 1` flag makes assertion or Python errors fail the shell command. Omit `--render` for faster construction and validation. `--out /absolute/directory` selects another output directory; `--calibration path.json` loads explicit wrist frames with the schema of the generated `calibration.json`.

The generated `.blend` contains only original dummy content. The repository's blanket `*.blend` exclusion also ignores this synthetic file; regenerate it locally with the command above. The script and the generated JSON/PNG evidence do not require private assets.

Open the blend file in Blender and select `WeaponRig` in Pose Mode to inspect the three bones. Names are shown in the viewport. Select `WeaponIKControls` to adjust the two custom influence properties or inspect the keyed action `WeaponGripInfluences`. Frames 1 and 48 are attached; frame 24 releases the orange left hand while the blue right hand continues following the prop. Green bars mark the wrist-target frames.

## Real hierarchy and coordinate convention

The armature is `WeaponRig`, with this bone tree:

```text
weapon
├── left_hand_weapon_ik
└── right_hand_weapon_ik
```

Both target bones have `weapon` as their actual Blender bone parent and are not connected end-to-end. The root rest transform is identity. The targets store wrist-joint frames, not palm centers. They inherit the weapon's animated transform. The synthetic armature has independent `upperarm_l → lowerarm_l → hand_l` and `upperarm_r → lowerarm_r → hand_r` chains under `arms_root`.

All calibration values use metres and the game's weapon frame: +X right, +Y up, -Z forward. These axes are retained in Blender rather than silently converted to Blender's usual Z-up presentation. Rotations in JSON are XYZW quaternions, normalized on input.

| Target | Weapon-local translation |
| --- | --- |
| `left_hand_weapon_ik` | `[-0.068, -0.112, -0.205]` |
| `right_hand_weapon_ik` | `[0.037, -0.095, 0.153]` |

The left orientation is the normalized quaternion `[0.70147073, 0.089098096, -0.089098096, 0.70147073]`, with the support wrist below the fore-end and the palm facing upward. The right orientation has basis columns X=`normalize([0,0.20,0.980])`, Z=`[-1,0,0]`, Y=`Z × X`. These match the runtime support/trigger wrist frames. Calibrating a different arm bind pose may require new wrist bases; simply moving a palm mesh is not equivalent.

## Base motion plus the attachment layer

`BaseArmMotion_preserved` is a real keyed FK action on the armature. It rotates both arm chains and both wrists through a nontrivial motion. `WeaponMotion` separately moves the `weapon` bone. Neither action is baked away or replaced when constraints are installed.

Each lower arm receives a two-bone IK constraint targeting the corresponding weapon child. Stretching is disabled. Each hand also receives a world-space Copy Rotation constraint targeting the same child. Both constraints are driven by that hand's independent custom property on `WeaponIKControls`:

- `left_hand_weapon_ik_influence`
- `right_hand_weapon_ik_influence`

The driver clamps the property to [0,1]. At 0, the original keyed arm and wrist motion remains exactly intact. At 1, the wrist's evaluated world position and orientation follow the weapon target. The demonstration animates the left influence from 1 to 0, holds it off during departure, and returns it to 1. Right influence remains 1. The helper rejects installing its named hand layer twice, preventing accidental duplicate constraints.

Blender's fractional IK influence blends its chain solution and its wrist rotation constraint. The runtime blends an independent authored hand pose toward the weapon target and then solves the arm. Their target frames and 0/1 endpoint contracts agree; intermediate joint trajectories are not asserted to be bit-identical. This distinction matters when matching a particular release arc. The authored free-hand path remains the source of departure motion.

The fixture uses rigid unit-scale objects. The runtime retains its own accepted uniform-scale rules. Do not use this fixture's equality checks to claim support for an existing rig with shear or nonuniform inherited scale.

## What is actually validated

The headless checks inspect the dependency graph's evaluated pose matrices, rather than checking bone names alone. At frames 1, 12, 24, 36, and 48 they verify:

1. Both target bones are real children of `weapon`, and their evaluated matrices equal the animated parent multiplied by the calibrated local frame
2. Influence 0 produces the exact same hand world matrices as muting the added constraints
3. Influence 1 reaches both weapon targets in position and orientation
4. Releasing left influence independently retains left FK motion while right remains attached
5. Influence 0.5 actually reaches the drivers, produces finite matrices, and produces a distinct partial result during the departure pose
6. The original FK action's channels and keyframe coordinates remain unchanged

The source action moves the left wrist by about 0.249 m. In the generated demonstration, its released frame-24 wrist is about 0.238 m from the moving weapon target, making release behavior visible rather than merely changing a control label.

`validation.json` records the evaluated world matrices and residuals. On Blender 4.3.2, the maximum full-influence target position error is approximately 1.9e-7 m and the zero-influence base matrix error is exactly 0. Numerical tolerances in the script allow solver/platform floating-point variation.

To check a saved file without rebuilding it, load that file headlessly and invoke `validate_fixture` from the helper against its `SyntheticArms`, `WeaponRig`, and `WeaponIKControls` objects. The helper's functions do not run `main()` when loaded with `runpy.run_path`.

`reopen-validation.json` records the same checks after loading the saved file. The underhand recalibration also verifies that the saved target rest matrices match the default calibration and that all arm, weapon, and influence action channels and keyframe values are identical to their values before recalibration.

## Ownership and provenance

Only this helper, this documentation, and generated original dummy fixtures are public deliverables. The helper neither imports nor modifies the optional private Soldier or HK416 packages. It does not change the game's arm solver, animation sampler, or reload timings. Any application to an existing production rig should be done on an explicit copy, after inspecting its bind axes and scale, while retaining the original animation action.

## Runtime presentation routing

The game evaluates `HandPresentation` before adding live weapon recoil and sprint offsets. Its pure `frames(body_frame, live_weapon)` function resolves the named target bones from the current weapon transform, while released hands use an independent authored reload frame. The caller explicitly shares body locomotion bob with the free frame; weapon-only recoil and sprint offsets do not enter that frame.

Attachment influence and finger articulation are independent channels. A left hand can have zero weapon attachment while its magazine-grip finger mode is fully active. The right hand remains attached through the current reload track. The left track reaches its authored support endpoint before its attachment influence rises, avoiding a second interpolation of the return path.

On cancellation, the outgoing free endpoint stays fixed while one constraint blend reacquires the weapon over 140 ms. A still-visible held magazine receives the same final wrist delta, preserving its grasp during that recovery. A seated magazine returns to the weapon frame. The arm solver and magazine renderer use the same public routing helpers, which are exercised by `tests/weapon_ik_pose_contract.rs`.

These transform tests do not establish correct anatomy or reference fidelity. Side and underside inspection of the actual skinned palm remains required; the current grip calibration is undergoing that separate visual review.
