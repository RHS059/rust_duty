# Physical lighting (opt-in, WIP)

`physical_lighting = 1` in `settings.cfg` enables an Unreal-style outdoor
pipeline. The default (`0`) keeps the established legacy key light
([viewmodel lighting](VIEWMODEL_LIGHTING.md)), so the shipped look and the CI
lighting verifier are unchanged. This is not Lumen or baked GI, and it has not
had artistic review.

| Stage | Implementation |
| --- | --- |
| Sun | Directional light, blackbody color, air-mass reddening; Lambert + GGX (Smith-Schlick, Schlick Fresnel, F0 0.04) |
| Sky light | Hemispherical sky/ground ambient (2-term SH), occluded by SSAO |
| Shadows | 3 cascades, bounding-sphere fit with texel snapping (no shimmer), normal-offset + slope-scaled bias, 3×3 PCF |
| Sky | Procedural horizon/zenith gradient, Mie halo, sun disk |
| Fog | Exponential height fog with directional sun inscattering |
| AO | Half-resolution SSAO from a packed depth prepass, 4×4 blur |
| Tonemap | Manual exposure + Narkowicz ACES, gamma 2.2 |
| Bloom | Threshold weight stored in alpha, quarter-res separable Gaussian, additive composite |
| Viewmodel | Same model on the CPU (distant-viewer specular); darkened when the camera is in shadow |

Default sun: the existing range key-light direction (≈54° elevation, clear
midday). GL2/GLES2-safe: shadow and depth are packed into RGBA8, with no float
or depth-texture sampling. If the shaders fail to compile, the game shows a
notice and falls back to CPU lighting with the same model (no shadows).

## Tuning (`settings.cfg`)

`sun_elevation`, `sun_azimuth`, `sun_intensity`, `sun_temperature`,
`sky_intensity`, `ground_bounce`, `exposure`, `shadow_distance`,
`shadow_resolution` (read at startup), `shadow_softness`, `fog_density`,
`fog_falloff`, `fog_height`, `fog_max_opacity`, `ao_radius`, `ao_strength`,
`bloom_threshold`, `bloom_intensity`, `specular_roughness`, `physical_lighting`.

## Code and verification

- `src/lighting.rs`: light model, ACES, cascade fitting. Unit tests cover the sun
  direction, ACES reference points, energy terms, cascade coverage and shimmer stability.
- `src/scene_lighting.rs`: legacy vs physical CPU shading. The original contract
  tests are unchanged.
- `src/render_pipeline.rs`: GPU passes and shaders (GLSL 100).
- Native check: Linux debug build under Xvfb (Mesa llvmpipe). Cast shadows from
  blocks, beams and stairs render; acne was fixed by world-texel bias. No
  Windows or real-GPU run and no performance measurement yet.
- The renderer runs on OpenGL (macroquad/miniquad). On Windows this is OpenGL
  via WGL, not Direct3D.
