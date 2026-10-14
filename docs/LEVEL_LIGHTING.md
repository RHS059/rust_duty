# Level lighting and selection

Ordinary launches open a level picker before any world is loaded or the player spawns. Choose Test Range or Cedar Junction with the mouse or Up/Down/Tab, then click Spawn or press Enter. Command-line `--level=range` / `--level=cedar_junction` sets the highlighted choice. Scripted captures and `--demo` keep unattended startup. An unavailable city returns to the picker with a retry message; the range remains selectable.

## Lighting approach

Epic's Lightmass documentation describes precomputed area shadows, sky occlusion and diffuse interreflection. Lumen instead maintains dynamic global illumination and reflections. These static levels use the former principle: our own deterministic triangle-ray bake, **not Unreal Engine, Lightmass or Lumen code**.

- Eight directional samples approximate a finite sun disk, with warm daylight.
- Thirty-two cosine-weighted hemisphere rays provide occluded cool sky illumination and one diffuse bounce using cached radiance on source triangles. Wall colors affect bounced light.
- Interior room lights have inverse-square attenuation and shadow rays. The range has lights at its overhead fixtures. Warm visible ceiling panels mark the sources.
- Adaptive triangle subdivision samples large surfaces; an area threshold prevents thin trim from accumulating unnecessary triangles. Identical baked vertices are merged afterward.
- Linear-light calculations precede an ACES-fitted highlight curve and sRGB encoding. This is a fixed exposure bake, not Unreal's complete ACES pipeline.
- Static geometry is lit once and stored in `assets/levels/<level>/lighting.bin`; it is never lit a second time by the loader. The unlit source geometry is retained separately.
- Held weapons sample sun/sky occlusion from world collision at the player's position. This conservative dynamic approximation does not use the static triangle bake.

Build with `cargo run --release --no-default-features --example bake_level_lighting`. Append `range` or `cedar_junction` to rebuild one level. Rebuild after changing geometry, sun, fixture placement or lighting parameters. Packaging includes both baked files; normal CI rebuilds them from its exact source revision. The dedicated lighting workflow commits the bake and CPU review images and captures both levels and the picker under Windows DX12 WARP.

The bake is diffuse-only and static: it does not add moving actor shadows, specular reflections, real-time GI, dynamic light changes or automatic exposure. Fine shadow detail is limited by vertex sampling. CPU geometry reviews are labeled separately from actual DX12 captures.

## Primary references

- [Epic: CPU Lightmass](https://dev.epicgames.com/documentation/en-us/unreal-engine/cpu-lightmass-global-illumination-in-unreal-engine): area shadows, color bleeding, sky occlusion, character lighting and lightmap resolution.
- [Epic: Lumen](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine): dynamic GI and reflections, including sky shadowing for interiors.
- [Epic: filmic tone mapping](https://dev.epicgames.com/documentation/en-us/unreal-engine/color-grading-and-the-filmic-tonemapper-in-unreal-engine): exposure and highlight response.
