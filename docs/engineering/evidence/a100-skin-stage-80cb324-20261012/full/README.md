# Complete original A100 skin-stage evidence

Four ordered binary parts retain the original version-2 skin/root diagnostic
archive for source `80cb324c744e3299d1dd2417c571cdc69c6e46cf`. They are a lossless
outer XZ encoding of the original ZIP_STORED archive, each at most 6 MiB.

Place `a100-skin-stage.xz.part000` through `a100-skin-stage.xz.part003`,
`manifest.json` and `reconstruct.py` together, or use these files in a checkout.
With Python 3:

```sh
python reconstruct.py --output-dir /path/to/new/a100-skin-stage-evidence
```

Use a new output directory. The script verifies ordered offsets, each part's
size/SHA-256, the combined XZ hash, the decompressed ZIP size/hash, and all 604
member CRCs. It neither extracts nor executes either retained ELF. Allow
approximately 650 MB for reconstructed ZIP/XZ output in addition to these
21 MB stored parts. Preserve binary file bytes during download.

| Representation | Bytes | SHA-256 |
| --- | ---: | --- |
| Combined XZ | 21,247,544 | `50f0625b040e5b0968ae0763f457387c19b204fd16be079f8649fe51244f0656` |
| Exact original ZIP_STORED | 626,639,135 | `7bc09f2d5ec8fd69d195c7a5dff4c023ebf944516a8ce2cfc0ac74ad4712a8b3` |

The full packet adds 44 raw corner streams and both compiled x86-64 ELFs to
558 byte-identical files shared with the compact packet. Its 604 entries expand
to 626,537,229 bytes; compact-only `COMPACT_PACKET.json` describes omissions.

See [the engineering report](../../../linux-a100-skin-stage-20261012.md) and
[direct full audit](../independent-full-audit.json). Strict image correctness
still fails; verified archive integrity does not change that verdict.
