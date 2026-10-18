# Official addon byte observation, v3

This separate original-code helper records hash-only diagnostics after the existing Windows native job has stopped. It neither imports the FBX addon nor changes any admission, dependency, numerical, audio, game, or capture gate. It cannot make a failed native step pass.

## Windows hostile-ZIP test fixture correction

The production observer is byte-identical to v2. That version's actual Windows run passed the timestamp-domain and real-file regressions but exposed a malformed-ZIP fixture defect. CPython 3.12.10 normalizes backslashes when `writestr` constructs a `ZipInfo` from a string, so the intended `x\evil` entry was stored as `x/evil`. The unexpectedly successful first case left a report that contaminated four later subcases. See [constructor normalization](https://github.com/python/cpython/blob/v3.12.10/Lib/zipfile/__init__.py#L341-L393) and [writer dispatch](https://github.com/python/cpython/blob/v3.12.10/Lib/zipfile/__init__.py#L1875-L1909).

The v3 tests explicitly set test-only `ZipInfo.filename` and `orig_filename` after construction, then verify the exact stored name in both raw headers and the reader's original name before calling production. Every negative case has its own temporary directory. Native-platform and modeled Windows separator cases both exercise the unchanged guards and require exact errors. No malformed case is skipped, normalized, or accepted by production.

## Windows timestamp-domain correction

The first actual Windows source-test run used CPython 3.12.10 and rejected ordinary fixture reads before native installers. Its path `lstat()` exposes creation time in `st_ctime_ns`, while its handle `fstat()` exposes metadata change time there. Comparing those values across APIs was invalid. The differing runner tuple values were not logged; this diagnosis is grounded in the exact CPython implementation and a source-only reproduction. See [path conversion](https://github.com/python/cpython/blob/v3.12.10/Modules/posixmodule.c#L2008-L2018), [handle conversion](https://github.com/python/cpython/blob/v3.12.10/Python/fileutils.c#L1027-L1041), and [fstat call chain](https://github.com/python/cpython/blob/v3.12.10/Modules/posixmodule.c#L10397-L10417).

Version 2 changes only the cross-API identity comparison. Windows binds volume ID, file ID, size, modification time, link count, and the explicitly shared creation time (`st_birthtime_ns`). Missing creation time or file identity fails closed. The original full path-before/path-after and handle-before/handle-after checks still include `st_ctime_ns`, so handle change-time mutations remain rejected. Linux retains its original full comparison. No Windows API wrapper, identity truncation, timestamp tolerance, or mismatch-ignore fallback was added.

The previously published v1 and v2 packages are retained. The actual v2 Windows run passed these identity-domain regressions. Genuine Windows verification of the v3 ZIP fixture correction remains pending; a local separator model is not a Windows execution result.

## Scope and trust boundaries

- The caller supplies the retained controller file, its existing raw SHA-256, work root, run ID, and attempt. Candidate and output paths are derived from that validated controller and checked against the current run. There is no arbitrary output-path option.
- The fixed report is `proof/public-evidence/official-addon-observation.json`. Creation is exclusive; existing reports, native files, and the original `summary.json` are never overwritten.
- The original native summary's raw hash, exact allowlisted error type, error hash, and outcome are retained. The observed failure fixture is `ContextError`, SHA-256 `8fbf4ddff747b03e580219fa0d2a3a80fb9b4c0664fdb437c1542514944ad737`.
- The official installer receipt, retained vendor checksum row/file, 405,138,423-byte Blender 4.3.2 Windows archive, installed executable, context manifest, and ten-file addon manifest are rechecked. The archive SHA-256 is `933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6`.
- The original retained Blender probe determines the installed addon directory. The helper does not start Blender, a subprocess, a download, an installer, or a network connection. It does not load Python code from the observed addon or proof packages.
- Limited retained process provenance checks bind the command, candidate directory, run, runner, current executable hash, terminal sidecar, completion fields, and both existing canonical hash domains. The controller command/context encoding has no final newline; the adapter environment encoding has one final newline. The original owner lock must be absent.
- These are diagnostic checks, not a repeat of full owned-process admission. Log/sample streams are not read. Self-hashes are not signatures. The probe hash is observed now; its bytes were not independently sealed by the terminal record.

## Output

Only the ten approved relative filenames, byte sizes, raw SHA-256 values, CRLF/bare-LF/bare-CR counts, diagnostic CRLF-to-LF hashes, unchanged expected raw pins, archive-versus-installed equality, and fixed outcome/provenance fields are emitted. Absolute paths, source contents, environment values, arbitrary exception text, logs, private URLs, and private assets are excluded. Build identity is hashed rather than copied.

Normalized hashes never satisfy a raw pin. Matching normalized hashes can suggest a newline explanation; they cannot establish it as an accepted source identity or admit native execution. A successfully written observation does not claim animation proof, native admission, or game capture.

If the already-created candidate lacks its original probe or retained process context, the report explicitly says `observation_unavailable`, with no addon rows and no proof claim. Invalid or contradictory inputs fail with a redacted error hash and nonzero exit status; they do not overwrite or soften the original failure. If an earlier failure prevented required controller/candidate/installer/summary inputs from existing, no substitute observation is fabricated.

## Bounds

- Ordinary absolute local paths only; traversal, Windows ADS/device names, symlinks, reparse points, hardlinked files, and changed file identities are rejected.
- Each addon file/member is at most 1 MiB. Installed plus archived selected addon bytes together are at most 4 MiB. The report is at most 32 KiB.
- Archive bytes are streamed and pinned before parsing, and pinned again on the same handle used to inspect the ZIP. The central directory is capped at 16 MiB and 50,000 entries before Python allocates its index. Exact/case-folded duplicate paths, unsafe names, selected nonregular entries, encrypted selected entries, and oversized selected entries are rejected. No archive member is extracted to disk.
- This deliberately bounded parser rejects ZIP64 and multidisk archives. Real compatibility with the pinned Windows archive has not been exercised in the local source-only tests; the next genuine Windows job will establish that result.

## Source-only verification

Run `python -I -B test_observe_official_addon.py`. There are 54 tests: all 52 v2 methods outside the malformed-name matrix are unchanged, that matrix now validates its raw fixture and isolates each negative, and one new test reproduces Windows writer normalization and raw-name retention. Tests use small files and ZIPs, and never run their fake binary or probe source. Test-only monkeypatches supply synthetic archive/manifest identities; no equivalent override exists in the production CLI. The exact retained failure summary remains a hash-only regression fixture. Identity coverage includes cross-file replacements, size/modification/link/creation changes, handle metadata-change mutations, path changes, missing identity fields, unchanged Linux comparison, and focused real-file read/mutation checks on the current platform.

The workflow exports the helper and tests using exact Git blobs, checks their separate hardcoded SHA-256 values, and runs tests before native installers. After existing native/game work and before bounded hash-artifact upload, an `always()` step rechecks the helper hash and writes the diagnostic report. Existing native/game steps and failure handling remain byte-identical. Artifact upload adds only the single explicit report path.

No actual Windows execution, official archive download, Blender run, Cargo run, or new proof/admission is represented by this preparation.
