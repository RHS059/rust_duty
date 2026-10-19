# One-time canonical weapon library bootstrap

This package contains no binary assets or credentials. It assembles the owner's single canonical editable weapon library from nine pinned existing sources. The permanent per-NLA FBX workflow reads only the resulting BLEND; it never reassembles these inputs.

Use Blender 4.3.2 and Python 3.11+:

    python prepare_inputs.py --repo /path/to/repo --output /tmp/weapon-assembly --accept-drive-warning
    blender -b --disable-autoexec --python /tmp/weapon-assembly/assemble_weapon_library.py
    blender -b --disable-autoexec /tmp/weapon-assembly/weapon_animations.blend --python /tmp/weapon-assembly/verify_weapon_library.py

`--accept-drive-warning` is authorized for these three source files by the owner's explicit approval on 2026-10-19. Downloading reuses the reviewed repository `tools/runtime_recovery_20261019/restore.py` downloader, which follows only Google's exact download warning form and checks pinned size and SHA256.

Publish only `/tmp/weapon-assembly/weapon_animations.blend` at `assets/authoring/weapon_animations.blend`. This path is overwritten for later authoring updates. Do not publish the nine source copies as new canonical files.

Expected structure: nine source sets, ten scenes, 666 preserved Actions, 67 explicitly mapped export clips, 27 packed images. `EXPORT_MANIFEST` and `ALL_ANIMATION_INVENTORY` are embedded text blocks. The exporter uses only the manifest's named NLA tracks and intended rig, arms, weapon, magazine and camera objects. Reference/helper geometry remains editable in the BLEND but is excluded from FBX selections. Historical revisions remain retained with fake users and archived tracks. Jump landing r8 is the existing approved two-key recipe on a retained r7 copy. Existing WIP and unavailable-feature labels remain explicit.

Outputs include `WEAPON_LIBRARY_REOPEN_VERIFICATION.json`. Validation is saved-file structural inspection and preservation, not a new numerical motion identity or runtime certification. Serialized BLEND bytes can differ across environments; record the actual runner output hash after structural checks rather than requiring the earlier cloud serialization hash.
