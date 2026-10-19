# Narrow corrections and limits

- Confirmed PR77 failure: SHA256 of `process host_binding differs` equals 255c614ba75ddc6ba26bcb310ffa6f021ee9b7f27be300370ae5faa1974b8587. Exact v5 PINS and artifact were verified before diagnosis.
- Use adapter.digest only for the two adapter-facing environment fingerprints. Keep workflow_core.digest and all existing context/build/config digests unchanged.
- Keep the authoritative semantic verifier unchanged; do not accept either encoding or normalize a mismatch away.
- Add a preinstaller existing-Python subprocess regression using real Commands.run and the unchanged full retained-process verifier. Portable tests simulate only the process boundary; they do not claim Windows execution.
- Preserve complete active-workflow behavior via an explicit composition base and a separate final workflow mapping. Rebinding game successor and final admission records is separate work.
- No raw private outputs, secrets, geometry or soldier assets are added or uploaded. Existing private evidence remains runner-local until teardown.
