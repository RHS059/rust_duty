# Resident vertex color: exact UNORM conversion candidate

This revision addresses one measured representation difference in the failed
A100 correctness run at `5f253fb0f60ec328d56cdd7fb19dbdca09c67b57`.
It does not establish that the full-image mismatch is fixed.

## Retained observation

The current and historical-normalization probe routes produced identical words
for all 108 selected vertex records. Relative to the CPU vertex route, 84 clip
position tuples and 29 color tuples differed. Every differing color component
was one positive float32 ULP; alpha was identical. Across all 432 color
components, the quantized byte was unchanged: the CPU path matched correctly
rounded `byte / 255`, while both resident routes matched
`byte * float32(1 / 255)`. The rounded reciprocal is `0x3b808081`.
For example, byte 99 yielded CPU word 1053214407 and resident word 1053214408.

All 44 PNG files remained identical to the original A100 run, which failed the
strict image gate on 18 pixels across 11 image pairs (maximum channel delta 3).
The clip-position discrepancy remains independently open. Selected diagnostic
vertices and instrumented entry points do not identify the actual raster
primitive responsible for every changed pixel.

Original compact packet SHA-256:
`883a01366cddd17cd42d7e284d939574c5a17fb5792674c21e2a1642600ff057`.

## Minimal production change

`color_byte` keeps its existing float-to-byte truncation, saturation and NaN
behavior. Only the conversion of that byte back to a normalized float changes.
The new `unorm8_exact(u32)` constructs the correctly rounded IEEE-754 word using
integer arithmetic, followed by a bitcast. It prevents a float division from
being replaced by multiplication with the rounded reciprocal.

For bytes 1 through 254, let `n = floor(log2(byte))`. The normalized significand
is the nearest integer to `(byte << (31 - n)) / 255`. Adding 127 before integer
division rounds to nearest; the odd denominator has no halfway cases. The
largest numerator including that addition is 4,261,412,991, below `u32::MAX`.
Bytes 0 and 255 have explicit endpoints. Lighting, transforms, normals, byte
quantization, blending, textures and resource lifetimes are unchanged.

## Discriminating checks

- A pure Rust test exhausts all 256 bytes against an independent float64 rational
  oracle rounded to float32, checks integer bounds, and demonstrates the old
  reciprocal-product discrepancy.
- Naga parses and validates the exact production shader and generated test
  shader. Source checks require unsigned integer input and a float bitcast.
- The existing explicit native resident test additionally compares all 256
  shader conversions with both the actual `Unorm8x4` vertex-fetch path and the
  rational oracle. Eight extra inputs cover negative, zero, tiny positive,
  saturated, infinite and NaN behavior. It saves every raw color word in
  `unorm-byte-report.json` before parity assertions.
- The original 27 synthetic image pairs, 21 renderer controls and 22 authored
  image/corner cases retain their existing acceptance conditions.

The exhaustive GPU conversion test is diagnostic instrumentation. Its success
would establish the conversion on that adapter/compiler, not full authored
image parity or performance. New source manifests identify this candidate and
its individual policy controls; all measured 43-, 46- and 48-file historical
classes remain separately admitted under their original hashes.
