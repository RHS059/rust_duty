Can AI build a game from footage alone?


## Cedar Junction city level

The default world is now an explorable American downtown assembled from the
[low-poly item collection](https://github.com/RHS059/low_poly_items): 16 enterable
buildings, furnished shops, 41 occupied floors, 25 stair connections, streets,
alleys, parking, a market plaza, and Cedar Commons park.

Choose **ENTER WORLD** at launch, or use `--level=cedar_junction`.
The original test range remains available with `--level=range`.

[Level guide and controls](docs/CEDAR_JUNCTION.md) ·
[Geometry review images](assets/levels/cedar_junction/review/) ·
[Build and validate the city](.github/workflows/build-city.yml)

![Cedar Junction overview](assets/levels/cedar_junction/review/overview.jpg)

## Weapon animation authoring

Update the same [canonical weapon BLEND](assets/authoring/weapon_animations.blend).
The [NLA export and runtime guide](tools/nla_export/README.md) explains per-track
FBX export, automatic runtime coverage, playback ranges, and inspecting preserved
historical Actions.

## Deterministic renderer benchmark

See [Cedar Junction benchmark](docs/performance/CEDAR_BENCHMARK.md) for the fixed
fly-through, exact submission/upload counters, optional GPU queries and strict
before/after comparison. CPU-only scene evidence is explicitly separate.
