# Historical source admission fixture

`skin-stage-source-663d191.zip` contains exactly the 48 original repository
source files in `performance_matrix.ARITHMETIC_SOURCE_PATHS`, read from commit
`663d1915341b18a4144bdcae918f16964ec54b18`. It contains no assets or binaries.
The same 48 blobs are also present in published commit
`80cb324c744e3299d1dd2417c571cdc69c6e46cf`, which can be used to reproduce the
fixture when the local implementation commit is unavailable.

- ZIP SHA-256: `f534904b8dae31637d6983576679e3d16f477a5ff0026da921e18ad1299e2c4d`
- Canonical path-to-file-SHA-256 digest: `b531276d331ff2addea10aec89eea7eb743cbab89858709194cdc8286fc32a96`
- Uncompressed source bytes: 1,114,484

The archive is a test-only immutable positive fixture for historical source
admission and witness roundtrips. Tests verify its archive hash, complete member
inventory, and original runtime digest before making a disposable Git checkout.
This avoids dependence on shallow CI history or the evolving live source tree.
Changed current source is separately required to fail admission and export;
this fixture does not grant it a historical runtime identity.

To reproduce, read each named file with `git show COMMIT:PATH`, then ZIP the
sorted paths with Python's `ZIP_DEFLATED`, compression level 9, member timestamp
`1980-01-01 00:00:00`, and `external_attr = 0o100644 << 16`.
