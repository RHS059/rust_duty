# Complete original A100 direct-viewmodel evidence

Three ordered binary parts retain the original source `aec1955e` full archive
as a lossless outer XZ encoding of its ZIP_STORED bytes. Each part is at most
6 MiB. Place `a100-direct.xz.part000` through `a100-direct.xz.part002`,
`manifest.json` and `reconstruct.py` together, or use their checkout paths.

```sh
python reconstruct.py --output-dir /path/to/new/a100-direct-evidence
```

Use a new directory. The Python 3 verifier checks part order/offsets, sizes and
SHA-256 values, combined XZ, decompressed original ZIP, and all 649 member CRCs.
It neither extracts nor executes retained game/test ELFs. Allow approximately
165 MB for output in addition to these 18 MB stored parts. Preserve binary bytes.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Combined XZ | 17,441,004 | `8a37433a5a5c49450d1b2da4551198d84bfe2ffc0d91811766ddb1c239288361` |
| Exact original ZIP_STORED | 142,867,383 | `b679f8d20ab9a855b6b136ef6d8e4515c4bd1980ed3242c192daa68dd2e0a5b4` |

The packet retains all four raw performance legs, source/build/controller inputs,
game and native-test ELFs, native fixture images, game screenshots and original
process/display/setup records. See [the report](../../../linux-a100-direct-viewmodel-20261012.md)
and [full raw audit](../independent-performance-audit.json). Earlier compact
records remain frozen; bounded native success does not waive the previous strict
arithmetic image failure or establish full-image/gameplay-wide correctness.
