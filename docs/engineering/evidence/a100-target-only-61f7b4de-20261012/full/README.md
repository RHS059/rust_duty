# Original target-only ABCCBA evidence

Three ordered binary parts retain the complete original source `61f7b4de`
A100 evidence as a lossless outer XZ encoding of its original ZIP_STORED file.
Each part is at most 6 MiB. Place `a100-target.xz.part000` through
`a100-target.xz.part002`, `manifest.json` and `reconstruct.py` together.

```sh
python reconstruct.py --output-dir /path/to/new/a100-target-evidence
```

Use a new directory. The Python 3 verifier checks part order/offsets, sizes and
SHA-256 values, combined XZ, decompressed ZIP, and all 693 member CRCs. It does
not extract or execute the retained ELF. Allow approximately 210 MB for output
in addition to these 19 MB stored parts. Preserve original binary file bytes.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Combined XZ | 18,505,480 | `70b31dd16bdf8ce1df059a3a578fe1906a0931212bc8d6c4bc626d71af1279a8` |
| Exact original ZIP_STORED | 185,810,810 | `fa415bf6904e7fe9ce6c3252b582dd522ca9ac5aa4dcc1c35b23366f6ec13f09` |

The packet retains all six raw runs, screenshots, original source/build/ELF,
launch/controller input receipts, and setup records. See [the report](../../../linux-a100-target-only-20261012.md)
and [independent raw audit](../independent-audit.json). These omission controls
are diagnostic evidence, not a usable visual optimization or image-parity pass.
