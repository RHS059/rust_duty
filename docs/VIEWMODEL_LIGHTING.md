# World-fixed viewmodel lighting

The range, authored arms, rigid weapon actors, legacy IK arms and procedural
fallback now use one world-space directional key light plus ambient fill. The
world direction toward the light is normalized `(-0.3, 0.8, 0.5)`, with the existing
`0.35 + 0.65 * max(dot(normal, light), 0)` response.

Previously the weapon's diffuse lighting was baked into vertex colors once at
load, before actor transforms. Arms used a constant camera-local light. The
range's cubes were unlit. Macroquad's default material ignores vertex normals,
so populating the normal field alone never repaired those disconnected paths.

The default material remains unchanged. CPU lighting now starts from immutable
albedo on every draw. Rigid normals use the inverse transpose of the complete
current actor transform, including nonuniform scale and separately drawn
magazines. Skinned normals retain their existing inverse-transpose bone palette.
For the origin-centered offscreen viewmodel camera, the shared world light is
rotated into the actual world camera basis, including pitch and camera recoil.
The geometry, authored transforms, animation selection, timing and source assets
are unchanged. Range cube faces and ramp triangles use explicit outward normals.
HUD, line overlays and muzzle effects retain their prior unlit behavior.

This is directional diffuse lighting, not a point-light or shadow implementation.
The cyan range fixtures remain decorative. There is no occlusion, shadow map,
light attenuation, specular reflection, tone mapping, or PBR change here.

## Verification

- `cargo test --locked`: camera basis equivalence, yaw/pitch/recoil, inverse
  transpose, skin/rigid normal handling, translation invariance, repeat-draw
  albedo preservation, and existing gameplay/animation regression tests
- `cargo clippy --locked --all-targets -- -D warnings`
- `python -m unittest discover -s tools -p 'test_*.py'`
- Complete generated asset verification and Windows/Linux packaging remain required
- Linux CI runs `tools/verify_lighting_capture.py` against the packaged executable
  under Xvfb. It captures the same frozen ready and reload poses at four cardinal
  headings and ±35° pitch, alongside the actual level pass. The checker validates
  light-space math independently, fixed silhouettes, and separate hand/weapon
  brightness response, then emits native images, contact sheets and JSON results

For a single diagnostic frame, add `--capture-lighting --capture-yaw=-90
--capture-pitch=0 --reference-viewport --viewmodel-time=0` to an explicit authored
asset/clip capture. Angles are degrees; default forward is yaw -90° along world -Z.
These flags freeze simulation for the diagnostic only and never contact updates.
