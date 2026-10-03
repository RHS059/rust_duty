# Rust Duty authored locomotion package

Keep `asset.vra`, `asset.vrs` and `asset.vrm` together. These are the unchanged
43-clip gameplay companions, including ready, entry, loop, phase-specific exit
bridges and settle. The optional diagnostic sequence is not included.

The repository stores the larger skin companion as deterministic `asset.vrs.gz`
for transport. CI verifies its compressed hash, decompresses it with a size
bound, and verifies the original `asset.vrs` hash before staging the ordinary
three-file runtime layout. Builds and updates include the decoded VRS, not a
runtime compression dependency.

`manifest.json` pins exact sizes and SHA-256 hashes and records sanitized source
provenance. `python tools/package_game.py verify --root .` checks the files,
binding CRCs and 43-clip contract before CI can publish a complete game build.
The source was evaluated at 480 Hz; the original private converter manifest had
a stale 240 Hz metadata field. No animation bytes were changed to correct it.

The project owner authorized distribution of these exact converted companions
with Rust Duty. Copyright remains with the original asset rights holders. The
project's MIT code license does not grant a separate right to extract, reuse or
redistribute these assets in other projects. Original BLEND/FBX sources and other
licensed assets are not included or authorized by this package's inclusion.

This package supplies locomotion only. New authored reload, ADS and firing
visuals are not included. Existing numerical parity evidence is not a claim of
native gameplay visual acceptance or retail-game animation parity.
