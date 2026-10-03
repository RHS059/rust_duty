"""Optional Blender-only preprocessing for the supplied untextured static test FBX.

Run with installed Blender, not ordinary Python:
  blender --background --factory-startup --python tools/prepare_fbx.py -- \
    private-assets/input.fbx private-assets/local.glb --neutral-material

Explicit --neutral-material replaces materials and omits vertex colors/textures.
This is intentionally lossy test preparation, not an FBX fidelity converter.
"""
import argparse
import sys
from pathlib import Path


def main():
    import bpy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--neutral-material", action="store_true", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must differ")
    if args.output.exists() and not args.force:
        parser.error("output exists; use --force for an intentional replacement")
    if args.input.suffix.lower() != ".fbx" or args.output.suffix.lower() != ".glb":
        parser.error("expected input.fbx and output.glb")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(args.input.resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        parser.error("no mesh objects")
    if bpy.data.actions or any(obj.type == "ARMATURE" for obj in bpy.context.scene.objects):
        parser.error("animation/armatures unsupported; export a deliberate static version first")
    if any(obj.data.shape_keys or any(m.type == "ARMATURE" for m in obj.modifiers) for obj in meshes):
        parser.error("morph/skinned geometry unsupported")
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    material = bpy.data.materials.new("Neutral test gray")
    material.diffuse_color = (0.38, 0.40, 0.42, 1.0)
    material.use_nodes = True
    material.use_backface_culling = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = material.diffuse_color
    shader.inputs["Metallic"].default_value = 0.0
    shader.inputs["Roughness"].default_value = 0.7
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(material)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output.resolve()), export_format="GLB",
        export_animations=False, export_cameras=False, export_lights=False,
        export_vertex_color="NONE", export_all_vertex_colors=False,
    )
    print("Prepared static neutral GLB; source FBX remains unchanged")


if __name__ == "__main__":
    main()
