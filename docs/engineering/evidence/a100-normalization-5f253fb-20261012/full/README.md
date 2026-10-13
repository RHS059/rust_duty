# Lossless full A100 evidence

These eight ordered binary parts retain the complete original A100 correctness
and vertex-probe archive at source `5f253fb0f60ec328d56cdd7fb19dbdca09c67b57`.
They are a lossless outer XZ encoding of the original ZIP, not a repacked or
filtered substitute. The original ZIP exceeds the ordinary GitHub single-file
limit; each stored part is at most 6 MiB.

## Reconstruct and verify

Download all eight `a100-full.xz.part000` through `a100-full.xz.part007` files,
`manifest.json`, and `reconstruct.py` into one directory, or use their files
from a checkout. Preserve their original binary bytes. With Python 3:

```sh
python reconstruct.py --output-dir /path/to/new/a100-evidence
```

The output directory must not already exist. The script verifies every part's
size, order, offset and SHA-256; concatenates the XZ stream; checks its hash;
decompresses the exact original ZIP; checks its size and hash; then validates
all 596 ZIP member CRCs. It neither executes the contained ELF nor extracts
archive members. Allow approximately 200 MB for the two reconstructed files,
in addition to these 46 MB stored parts.

A manual equivalent is to concatenate the parts in numeric order, verify the
XZ hash below, decompress with XZ, and verify the original ZIP hash. Do not
concatenate by an unordered directory listing.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Concatenated XZ | 46,171,336 | `dd7c707ec16d784ffbf02792ead7636be20dee8956e3e70b7b775a169e3a2d6d` |
| Exact original ZIP | 147,411,430 | `dd8b187a5c6077a8998eb8caecd356ffebc843678ee67ae5a3a03489c66effdb` |

The original ZIP includes the 44 raw corner streams and compiled ELF omitted
from the compact packet, along with the unchanged source/build/process/image
and probe evidence. Its 596 files expand to 615,496,986 bytes. The compact and
full packets share 551 byte-identical files; only the compact packet contains
its explanatory `COMPACT_PACKET.json`.

See [the engineering report](../../../linux-a100-normalization-probe-20261012.md)
and [the independent full-byte audit](../independent-full-audit.json). Strict
image correctness still fails. Archival integrity is not a correctness pass.
