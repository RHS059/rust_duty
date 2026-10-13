# Original resident ADS diagnostic artifact retention

This directory preserves the exact original artifacts from [run 38247668699](https://github.com/RHS059/rust_duty/actions/runs/38247668699), source `2a1776a46fbcd9ad95371ea3ba49ab272a742c58`. This is retention only: no new execution, analysis acceptance, source change or waived gate.

| Original artifact | Bytes | SHA256 | Original expiry (UTC) |
|---|---:|---|---|
| 11747654555, resident-ads-all-attempt-1 | 42,432,817 | `893d34d04675678ca4f78de3ab970094b12787d7faa363fc291f75b31b901a0b` | 2026-10-19 12:46:00 |
| 11747314755, resident-ads-reports-attempt-1 | 297,639 | `d749f5220070d0c02f67f7c3f2c801ccba33a32322f5829e51ecd58830174599` | 2026-10-19 12:46:07 |

The full ZIP is split into seven ordered binary parts without modifying any original byte. Download all `resident-ads-all.zip.part000` through `part006`, `retention-manifest.json`, `resident-ads-reports-attempt-1.zip` and `reconstruct.py` into one directory, then run:

```sh
python reconstruct.py --output /path/to/new/resident-ads-all-attempt-1.zip
```

The script refuses an existing output, verifies each part and the reconstructed ZIP against the original GitHub digest, checks all 4,714 ZIP entry CRCs, and verifies the separate 26-entry report ZIP. It does not extract or execute retained contents. Allow approximately 43 MB additional output space. [The archive index](archive-index.json) records every member's size and SHA256; [the retention manifest](retention-manifest.json) binds artifact IDs, original digests, parts and integrity checks.

The archive contains 553 original PNGs per resident policy, image/gameplay/time sidecars, both original executables, two 131-file source variants and build/process/input/output receipts. The smaller report artifact is preserved separately and unchanged. The existing diagnostic's source-visibility failure and lack of performance/image-tolerance acceptance remain unchanged; this retention commit does not rerun its predicates or reinterpret its results.

Both downloaded original hashes match GitHub's artifact metadata. All entry CRCs and paths pass; inventory and credential-pattern inspection found no private soldier asset payloads or credentials. The historical source-only fixture elsewhere in the repository is distinct from these raw diagnostic archives.
