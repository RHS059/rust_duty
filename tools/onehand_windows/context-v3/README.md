# Context v3 source preparation: exact official Windows addon profile

This is fresh source preparation in the replacement workspace. It is derived from the complete hash-verified published context-v2 at immutable commit `01e3d821d197799a342b7738b84e835b11197f24`; it is not asserted byte-identical to the lost incomplete preparation. The context-v1/v2 packages remain unchanged.

## Exact evidence and profile

The diagnostic report from run `39107154529`, job `117615400667`, is 9,422 bytes with SHA-256 `5ee21d576be9af34c7b4095352aca1b4fde329eca23b79b6f12a189edc9d800a`. Its retained artifact is 5,181 bytes with SHA-256 `2e23f39ca4a7f42f27338e34a51970237bdf04242e9770b346876ef36ed5e9c0`. The report proves that all ten installed raw addon files equal the exact official Windows ZIP members. The ZIP is `blender-4.3.2-windows-x64.zip`, 405,138,423 bytes, SHA-256 `933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6`; the observed vendor-checksum-file identity is retained in the profile.

The only runtime profile is `blender-4.3.2-windows-x64-official-crlf-v1`, schema `rust-duty-windows-official-fbx-pins/v2`. Its ten whole raw hashes and exact byte/newline counts are fixed. Linux LF files are rejected by this profile. Historical Linux profiles are preserved in predecessors. No normalized raw hashes, hash alternatives, platform autodetection, on-run pin generation, or installed-file repair are accepted.

`reconstruct_windows_profile.py` is an explicit local evidence-preparation tool, never called by the runtime resolver. It verifies the predecessor freeze and exact observation, reads exact historical LF source, reconstructs CRLF in memory, and requires all ten entire raw hashes, sizes, CRLF counts and zero bare LF/CR counts to match the observed archive before deriving any function slices. It does not write installed files. `RECONSTRUCTION_EVIDENCE.json` contains only hashes/counts; no full addon source is included in this package.

## Raw-data versus runtime-source contract

- `files`: SHA-256 of entire raw file bytes.
- `raw_functions_sha256`: SHA-256 of UTF-8-encoded AST line slices, including original CRLF and decorators, from the first decorator/function line through `end_lineno`.
- `loaded_functions_sha256`: SHA-256 of the UTF-8 result of `inspect.getsource(function)`. Python's source loader returns universal-newline text; this distinct runtime-source domain retains the two original loaded hashes.

The raw function hashes are `d4ff67c4e021e56d0252bee2b71e32667764620ab6faa8899a11bd2778c6ec44` for `blen_store_keyframes_multi` and `d4a7f77069ec1c25036cf6760558dc42ceed0b4e63fc0ffa2524e5fc5f267264` for `blen_read_animations`. Their loaded-source hashes remain `793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e` and `757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2`, respectively.

All whole raw files are verified before raw slices; raw files are rechecked before loaded origins/functions. The resolver rejects shadow file/spec/code origins. It additionally compiles the entire exact verified importer without executing it and compares the selected top-level code objects with live functions on the same interpreter, with `dont_inherit=True, optimize=0`. This rejects same-origin in-memory code mutation. There is no stored bytecode hash or cross-Python-version bytecode expectation. The existing `functions_sha256` return field continues to mean the loaded-source map; separate raw/profile/domain fields and `live_function_code_checked` make the distinction explicit.

`LOADED_SOURCE_EVIDENCE.json` and the tests demonstrate a real bounded authored CRLF module import whose `inspect.getsource` bytes use LF while its on-disk bytes stay CRLF. The two audited functions are separately checked using code objects compiled from the exact entire reconstructed file without executing the addon module or calling either function. This is source-domain compatibility evidence, not actual Windows execution or animation proof.

## Unchanged production contract

`candidate_context.py`, `production_assembler.py`, `pinned_assembler.py`, `pinned_transport.py`, `NATIVE_HELPER_PINS.json` and `verify_freeze.py` are byte-identical to context-v2. Candidate-context schema remains v2. Metadata projection, authored/source/art contracts, all 4,240 times, 67 chunks, 12 blocks, nine focus times/four offkeys and strict numerical bounds remain unchanged. No motion proof was rerun. Native producer/helper and runtime consumer loaded-function receipt constants require no changes; their package dependency pins must bind this fresh source freeze separately.

## Verification and limits

Portable source CI invocation, from this package: `PYTHONDONTWRITEBYTECODE=1 python -B test_windows_addon_profile.py`. It uses only tiny authored temporary modules, without Blender or historical source payloads.

Local recovered-source invocation: `PYTHONDONTWRITEBYTECODE=1 python -B run_source_preparation_tests.py`. The runner verifies the available recovered context, metadata, assembler boundary, Windows-profile and reconstruction tests. The original complete 132-test historical suite was **not** rerun: 73 dynamic assembler tests and two direct dependent tests require exact unpublished historical fixtures absent from the restored immutable tree. Those omissions are recorded in `RESULTS.json` and never counted as passing or replaced with mocks. Existing strict assertions remain in the retained test source. Local fixture path adaptations are test-only.

`SOURCE_DIFF.patch` records the exact source/document difference from context-v2. `MINIMAL_DIFF.json` binds before/after identities and additions; generated records/logs are separately identified. `ALLOWLIST.json` and `PINS.json` freeze the complete flat source-only publication candidate. The allowlist's false authorization marker means this package does not itself grant publication permission. No private URLs, full addon files, assets, installed binaries, or native outputs are included.

No installation, Blender/native execution, CI dispatch, publication, native admission, runtime parity, artistic approval or activation was performed. Fresh independent review and actual Windows source/runtime admission remain separate gates.
