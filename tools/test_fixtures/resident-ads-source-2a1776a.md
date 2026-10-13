# Historical resident ADS source fixture

`resident-ads-source-2a1776a.zip` contains the 131 original source inputs selected
by `run_cpu_image_preservation.PRODUCTION_PATHS` at commit
`2a1776a46fbcd9ad95371ea3ba49ab272a742c58`. These source bytes reproduce the
existing resident ADS diagnostic's closed production identity. No asset,
executable, or new admission permission is included.

- ZIP SHA-256: `1cde55bca938ebe6c6afc942b88824e93d12620ec7814e467250cbb6aa95c8b6`
- Canonical path-to-file-SHA-256 digest: `2a6a534aec6e3a6053ed6584dac497e38f85fabcf47aecf64c209bc925460b17`
- Uncompressed source bytes: 4,889,125

The test-only loader verifies the fixed archive hash, unique member count, and
complete path-to-source digest. Tests create a disposable historical Git fixture
for positive scheduling admission and separately require current source to be
rejected. Source identity allowlists and the diagnostic are unchanged.

To reproduce, obtain the production paths with `git ls-tree -r --name-only`
at the pinned commit, read their bytes with `git show COMMIT:PATH`, then ZIP
sorted paths using Python `ZIP_DEFLATED`, compression level 9, member timestamp
`1980-01-01 00:00:00`, and `external_attr = 0o100644 << 16`.
