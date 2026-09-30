# Original multi-record asset fixtures

The eight complementary tests in `tests/asset_quality_regressions.rs` generate
all geometry, material values and pixels in memory. They contain no model data.
Three heterogeneous meshes total 10 vertices, 12 indices and 24 RGBA bytes.
An independent Python cross-check gives 552 file bytes and payload CRC32 63771b31.
The test serializer uses an independent MSB-first CRC algorithm, while production
uses reflected LSB-first CRC. Temporary-file tests use only unique test directories.

Run `cargo test --locked --test asset_quality_regressions` and the normal full suite.
