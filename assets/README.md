> Intermediate source-only update: the supplied HK416 was verified locally, but its model binary and new screenshots are not in this commit. The game uses its procedural fallback until the separately authorized single asset upload finishes.

# Asset rights are separate from source-code licensing

`weapons/hk416a5.vrm` is the single converted, untextured HK416A5 test model
supplied by the project owner. The owner confirmed artist permission to include
this specific converted weapon in the public game repository. Permission for
one model does not authorize uploading an artist's purchased library.

The MIT license covering this project's code does **not** apply to this model.
Copyright remains with its original rights holder. Do not assume permission to
extract, reuse, or redistribute it in another project. No license text or artist
identity was supplied, so no broader grant or attribution is invented here.

The original FBX and the local GLB intermediate are excluded from Git. The custom
container keeps usable geometry and UVs; it is reversible and is **not** encryption,
DRM, or proof of license compliance. Artist permission, not the format, determines
which distributions are allowed.

No textures were supplied. Its current gray surface is an original placeholder.

## Reproducing the authorized untextured test conversion

Blender 4.3.2 imported the supplied FBX in metres. Its 30 mesh objects were kept;
cameras/lights were omitted. Explicit neutral preparation replaced material
assignments and omitted vertex-color attributes because this test requests an
untextured gray weapon. It is a deliberately lossy surface conversion, not a
claim that all source material properties survive.

```sh
blender --background --factory-startup --python tools/prepare_fbx.py -- \
  private-assets/hk416a5.fbx private-assets/hk416a5-local.glb --neutral-material
python tools/vrpack.py pack private-assets/hk416a5-local.glb \
  assets/weapons/hk416a5.vrm --translate 0 -0.030 -0.150
```

Blender's GLB exporter converts source Z-up coordinates to glTF Y-up. The packer
then keeps scale 1 (metres), barrel toward -Z, and offsets the static weapon by
(0,-0.030,-0.150) metres for this game's viewmodel. The runtime adds its own hip/ADS
pose, bob and firing kick. Current geometry: 84,926 vertices, 98,522 triangles,
30 parts, no textures. Whole-weapon reload motion is a placeholder; there are
no rigged hands or mechanical magazine/bolt animations.
