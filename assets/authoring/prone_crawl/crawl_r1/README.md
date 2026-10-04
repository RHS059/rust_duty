# Four directional HIP crawl segments, first WIP

These are four nonlooping observed segments. No loop endpoints have been approved, and no cyclic closure is forced. Left is explicitly a short partial segment.

Source: `5KM0XSKxTWw.mp4`, SHA256 `cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e`, native 1280x720 at 60 fps. Source validation and half-open ranges were supplied by [Aella](https://github.com/RHS059/dot_chat/pull/1#issuecomment-5983841299):

- `prone_crawl_forward_segment_r1`: [4932,5173), 241 samples
- `prone_crawl_backward_segment_r1`: [5280,5509), 229 samples
- `prone_crawl_right_segment_r1`: [5628,5767), 139 samples
- `prone_crawl_left_segment_r1`: [5844,5899), 55 samples

Each Action starts at Blender frame 1. Source frame = first source frame + Blender frame − 1. Action first-to-last duration is (sample count − 1)/60 seconds; displaying every sample once produces sample count/60 seconds. There is no retiming, repeated segment, mirrored direction, synthesized cycle, or inferred exit.

## First-candidate method and honest limits

The author inspected source images at 12-native-frame spacing, retaining exact interval endpoints. `source_axis_witnesses.json` records manual leading-barrel and longitudinal-axis selections in original pixel coordinates, with approximately 16-pixel selection uncertainty. These are WIP pose-construction witnesses, not an independent three-physical-landmark scoring protocol. The rear guide is deliberately a virtual axis aid, not a claim that the shotgun breech is homologous to an HK416 sight or charging handle.

Shape-preserving interpolation produces pose targets at every native frame without altering source timing. A bounded fixed-camera fit of the accepted rigid viewmodel translates and pitches/yaws `righthand_prop`; model geometry, camera, grips and all original data remain unchanged. The fit's tiny numerical residual only describes two construction guides. It is not an animation score and does not establish matching hand articulation or overall visible shape.

This concrete editable first WIP is intended for genuine Eevee Viewport Render Animation and independent visible-motion review. Rendering is presently blocked on authorization clarification, so no source/model preview, visible match judgment, or runtime readiness is claimed. Do not treat the structural checks as artistic acceptance.

## Preservation and reproduction

Frozen input is the entry-only BLEND from `ca133d8b501aa5698bd6a5f56e7721e67c7a4184:assets/authoring/prone_crawl/halcyon_prone_crawl_r1.blend`, SHA256 `793546897db5634fca6ba6da7cefd5240e3712932c239bbabea7dfaa0f03419e`, 104 Actions. The current packed BLEND is in the parent directory and contains 108 Actions. All 104 original Actions, including entry, are unchanged; original rig, meshes, drivers, constraints, textures, cameras, NLA and default state are preserved.

Run Blender 4.3.2 with `--background --factory-startup --disable-autoexec FROZEN_ENTRY.blend --python-exit-code 1 --python author_crawl.py -- crawl_design.json NEW_OUTPUT.blend`. The recipe refuses overwrites and asserts input SHA256. `validate_source_structure.py` reopens the result read-only with the supplied baseline fingerprint and four expected new Action names. `check_segments.py` checks all evaluated bone matrices and bone-origin attachment drift. It does not render, save, or substitute for visible review.

`build_crawl_design.py` is the optional NumPy/SciPy witness-to-pose reproduction. It uses `model_guides.json` and the manual source observations embedded in the script. Hidden anatomy and other views are outside this assignment. No new ADS Actions, source cuts, shared inventory, runtime binding, production export or Colab changes were made.
