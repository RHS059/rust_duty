# Original visible/hidden viewmodel ABBA evidence

Three ordered binary parts retain the complete original source `ca03e841`
A100 evidence. They are a lossless outer XZ encoding of the original
ZIP_STORED archive; each part is at most 6 MiB.

Place `a100-viewmodel.xz.part000` through `a100-viewmodel.xz.part002`,
`manifest.json` and `reconstruct.py` together, or use these files in a checkout.
With Python 3:

```sh
python reconstruct.py --output-dir /path/to/new/a100-viewmodel-evidence
```

Use a new output directory. The verifier checks order, offsets, each part's
size/SHA-256, the combined XZ hash, decompressed ZIP size/hash and all 672 member
CRCs. It neither extracts nor executes the retained game ELF. Allow 150 MB for
reconstructed files in addition to the stored 14 MB parts. Preserve binary bytes.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Combined XZ | 13,570,556 | `8d7947bfd9d943f49df098f07993106196a4a6552a8f545179fa44e8a1ecff5d` |
| Exact original ZIP_STORED | 131,468,206 | `f62abf0f70c8ce9db540b3630b5bf2677ba40bd4ef33ec4f4dbf7f4d697d90c5` |

The packet retains the four successful runs' raw CPU/GPU/process records and
screenshots, original source/build/ELF and launch inputs, both failed startup
attempts, and display/XKB/startup-race repair records. Nothing is removed or
reclassified as passing. See the [engineering report](../../../linux-a100-viewmodel-isolation-20261012.md)
and [independent audit](../independent-audit.json). This layer-omission diagnostic
is not a usable visual optimization or a strict image-parity pass.
