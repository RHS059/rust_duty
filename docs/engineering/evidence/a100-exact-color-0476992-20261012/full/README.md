# Complete original A100 exact-color evidence

Four ordered binary parts retain the original correctness/conversion archive
for source `047699250fdcd98700caff66cbc86c4adf585b87`. They are a lossless outer
XZ encoding of the original ZIP_STORED archive. Each part is at most 6 MiB.

## Reconstruct and verify

Place `a100-exact-color.xz.part000` through `a100-exact-color.xz.part003`,
`manifest.json` and `reconstruct.py` together, or use these files in a checkout.
With Python 3:

```sh
python reconstruct.py --output-dir /path/to/new/a100-exact-color-evidence
```

Use a new output directory. The script verifies ordered offsets, each part's
size and SHA-256, the concatenated XZ hash, the decompressed ZIP size and hash,
and all 603 ZIP member CRCs. It does not extract or execute either retained ELF.
Allow approximately 650 MB for reconstructed ZIP/XZ output in addition to the
21 MB stored parts. Download binary files without transforming their bytes.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Concatenated XZ | 21,177,536 | `fb2055d959c44f576cd9e14a9a453e020f745ad38cac66fd0af92f45e68b7dea` |
| Exact original ZIP_STORED | 625,606,155 | `7a75575364990e4963f012e2ee8dad5a75a14595a351f3c4d618033cdbbc6237` |

The full packet adds 44 raw corner streams and both compiled x86-64 ELFs to the
557 byte-identical files shared with the compact packet. Its 603 entries expand
to 625,504,417 bytes. The compact-only `COMPACT_PACKET.json` explains omissions.

See [the engineering report](../../../linux-a100-exact-color-20261012.md) and
[direct full-byte audit](../independent-full-audit.json). The isolated conversion
contract passes; strict renderer image correctness still fails. Verified archive
integrity does not change either gate's verdict.
