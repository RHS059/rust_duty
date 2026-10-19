# Official addon observer v7: exact probe producer/consumer contract

This is a source-only successor to observer v6. It accepts only the current
`rust-duty-official-blender-host-observation/v2` exact field set and probe SHA
`cef34876a036fec04d520e835d95f8a3fea7a51cad23bb9140efdae13694a350`.
The orchestration manifest remains exact-pinned; any successor composition must
rebind that literal SHA to its final reviewed manifest, then rerun every test.

The native tuple requires exactly system/release/version/machine, bounded strings,
Windows, AMD64, and the N6/O9 release/version grammars. The retained supervisor
command and terminal must agree on all four fields and run/runner/build identity.
The native probe and supervisor must agree on system/version/machine; release is
intentionally role-specific, as required by the accepted N6/O9 contract. No
aliases, defaults, normalization or environment-derived identity is accepted.

All existing official archive, vendor checksum, installed executable, Windows
raw addon profile, file-handle identity, raw-byte, process completion, owner-lock,
environment digest, read-size, path, ZIP and public-report gates remain in force.
A successful diagnostic report keeps schema `rust-duty-official-addon-observation/v1`.
It never grants admission or changes the original native outcome.

Failure stdout now has the separate bounded schema
`rust-duty-official-addon-observation-failure/v1`. It contains only static
allowlisted error code/category/type, an exact UTF-8 exception-string SHA256 when
available, and up to eight source-owned frames. Frames require exact registered
code-object identity, never a matching untrusted filename. Paths, exception
strings, environment, locals, external frames, geometry and addon source text
are not emitted. Failure remains exit status 1. See the preparation directory's
WORKFLOW_INTEGRATION.md for capture/upload requirements; no active workflow was
changed here.

## CPU verification

Run each inherited suite (54 and 19 tests respectively):

    python -I -B test_observe_official_addon.py
    python -I -B test_windows_profile.py

Run the 20 producer/consumer and privacy tests with the actual reviewed
orchestration source directory (no fallback, skip or synthetic source override):

    python -I -B test_probe_contract.py --orchestration <exact-source-root>

The last suite verifies actual PINS and probe bytes, executes the complete exact
probe main with inert Windows/ctypes/Blender module fixtures, then consumes its
JSON in the real observer. Only host APIs and fake file payloads are synthetic;
the schema-producing code and bound source manifest are actual package bytes.
It additionally tests tuple/role mutation, stale source pins, output privacy,
static frame provenance and exact long-exception hashes.

No native Windows/Blender execution, successful animation, game capture,
rendering, installation, external write or audible output is claimed.
