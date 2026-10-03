"""Make a portable publication copy without changing animation or rig data.

Input must be the identified final source. It is never overwritten. Source UI
recovery texts are removed, because they are unrelated to export. No embedded
Text script is run. This command is only needed to repeat the packaging step.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_integrity import snapshot

EXPECTED_SOURCE = "b8fc6b9ca7342fd70deb6479d1b699a91cc884edc446ae5f8ddc82145eed1e18"
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
assert bpy.app.version == (4, 3, 2), "Use Blender 4.3.2"
source = Path(bpy.data.filepath).resolve()
assert hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED_SOURCE
assert not args.output.exists() and not args.report.exists(), "Refuse overwrite"
assert source != args.output.resolve()
before = snapshot(bpy)
removed_texts = [text.name for text in bpy.data.texts]
for text in list(bpy.data.texts):
    bpy.data.texts.remove(text)
for index, image in enumerate(bpy.data.images):
    assert image.packed_file, "All source images must be packed"
    # Clear full fixed-size path buffers before shorter names, including stale tails.
    image.filepath = " " * 1023
    image.filepath = f"//textures/arms_{index:02d}.png"
    for packed in image.packed_files:
        packed.filepath = " " * 1023
        packed.filepath = image.filepath
assert not bpy.data.libraries, "Unexpected linked library"
for scene in bpy.data.scenes:
    scene.render.filepath = " " * 1023
    scene.render.filepath = "//renders/locomotion"
# File-browser UI paths can survive inside a .blend even in background mode.
for screen in bpy.data.screens:
    for area in screen.areas:
        for space in area.spaces:
            if space.type == "FILE_BROWSER" and space.params:
                space.params.directory = b"//"
                space.params.filename = ""
# Stale work-session narratives are not part of the animation data.
for scene in bpy.data.scenes:
    for key in ("pose", "workflow", "locomotion_checkpoint", "locomotion_status"):
        if key in scene:
            del scene[key]
rig = bpy.data.objects["Arms"]
for key in ("recovery_stage", "magazine_stage_recovery", "captured_magazine_recovery", "instructions"):
    if key in rig:
        del rig[key]
text = bpy.data.texts.new("RD_LOCOMOTION_README")
text.write("Portable locomotion authoring source. See sibling README.md and export_config.json.\n"
           "All 61 Actions and seven NLA tracks are retained. Reload Actions are archived\n"
           "context, not the authoritative current reload master. No walk Action exists.\n"
           "Use Blender 4.3.2 with auto-run disabled. Packed textures are self-contained.\n")
assert snapshot(bpy) == before, "Animation, NLA, driver or packed image data changed"
args.output.parent.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), check_existing=False, compress=True)
# Reopen the actual saved bytes, not only the in-memory scene.
bpy.ops.wm.open_mainfile(filepath=str(args.output.resolve()), load_ui=False, use_scripts=False)
bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
assert snapshot(bpy) == before, "Reopened source integrity mismatch"
drivers = [curve for obj in bpy.data.objects if obj.animation_data for curve in obj.animation_data.drivers]
assert len(drivers) == 185 and all(curve.driver.is_valid for curve in drivers)
assert hashlib.sha256(source.read_bytes()).hexdigest() == EXPECTED_SOURCE
report = {
    "schema": "rust-duty-locomotion-source-integrity/v1",
    "blender": bpy.app.version_string,
    "original_final_source_sha256": EXPECTED_SOURCE,
    "portable_source_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    "preserved": before,
    "action_count": len(before["actions"]),
    "nla_track_count": sum(len(data["tracks"]) for data in before["nla"].values()),
    "valid_driver_count": len(drivers),
    "original_source_unchanged": True,
    "reopened_integrity_verified": True,
    "removed_embedded_text_names": removed_texts,
    "sanitization": ["Packed texture paths made relative", "Render and file-browser paths made relative",
                     "Stale session narratives removed", "Embedded recovery/UI Text blocks replaced by README"],
}
args.report.write_text(json.dumps(report, indent=2) + "\n")
print("PORTABLE_SOURCE_VERIFIED", args.output.name, report["portable_source_sha256"])
