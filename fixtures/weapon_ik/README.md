# Original weapon IK fixture

Generated entirely by `tools/create_weapon_ik_rig.py`; no external assets or animation are included.

- `hierarchy.json`: actual armature parentage and independent controls
- `calibration.json`: weapon-local wrist frames shared with the runtime
- `validation.json`: evaluated Blender transform evidence at influences 0, 0.5 and 1
- `attached.png`, `left_released.png`, `reattached.png`: original dummy previews
- `weapon_ik_demo.blend`: locally generated reviewable rig; ignored by the repository's general binary-asset rule

Regeneration and rig details are in `docs/WEAPON_IK_RIG.md`. Left is orange, right is blue, and weapon wrist targets are green. The grey rectangular prop is deliberately generic.
