# Complete original coalescer A100 evidence

Download all 13 `a100-coalesced.xz.part000` through `part012` files, `manifest.json`, and `reconstruct.py` into one directory. Run:

```sh
python reconstruct.py --output-dir /path/to/new-empty-output
```

Python 3 standard libraries are sufficient. The script checks ordered part sizes and SHA256 hashes, the combined XZ, exact decompressed original ZIP, all 706 entries and CRCs. It neither extracts nor executes archive contents, and refuses an existing output directory. Allow at least 1 GB of free disk space in addition to the downloaded parts. Do not run retained executables merely to inspect evidence.

- XZ: 78,987,868 bytes; SHA256 `f83ac8e2f63d25cf2b2a74e88ce2cc2b55fba469840185a98cad96e970996c47`.
- Original ZIP: 839,406,313 bytes; SHA256 `0453642bac3a105163fa77d0b25ff1e03c4df9e66a9054d4600aeb6981771973`.
- All 13 parts have SHA256 and Git blob SHA1 entries in the manifest.

Local compression reproduces the original remote XZ exactly. The original ZIP was recovered using hash-verified retained bytes and CPU reconstruction; every final byte matches the independent original archive SHA256. The package is self-contained and needs no Colab session or other workspace. The separately retained compact and intermediate receipts remain unchanged.

Independent streaming verification checked every part, exact decompressed bytes against the original ZIP and all CRCs without another large disk copy. See `../independent-publication-parts-review.json` and the final report for provenance and acceptance limits.
