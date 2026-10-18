# Direct approved-animation delivery

The Windows delivery workflow consumes existing approved runtime assets at their stable filenames, compiles the game with Cargo, and stages the playable package. Historical numerical fidelity and capture reports do not admit or block this route.

Stable packs are `assets/low_vault`, `assets/prone_entry` and `assets/onehand`. Their exact paths/clip names remain in `assets/animations.cfg`. The stager copies each configured asset, its VRS/VRM companions, and its configured receipt/camera file. Replacing an existing file does not require a new slot-hookup check. Missing or malformed files and ordinary compilation failures still fail.

Run from a prepared Windows checkout:

    python -I -B tools/onehand_windows/direct-delivery-v1/run_delivery.py --root GAME_ROOT --work FRESH_WORK_DIR --cargo CARGO_EXE --rustc RUSTC_EXE --source-commit EXACT_COMMIT

The default route performs no Blender execution, sampler build, numerical proof, dep-info closure reconstruction or gameplay capture. Game compilation uses the existing `audio,legacy-macroquad,wgpu-runtime` features and `x86_64-pc-windows-msvc` target. The existing Windows Job adapter owns each command and descendants; resource limits remain enforced.

Published high-mantle constants are enabled for the recovered exact original receipt and exports. Idempotent binding records any source/cfg changes in GAME_CANDIDATE.json, so a source commit is never presented as an unmodified checkout when files changed. The high-mantle loader retains asset/receipt hashes, native60fps/256-subdivision timing, actor basis and format/companion decoding. Its historical numerical-proof fields are no longer runtime requirements. Original receipts can be retained unchanged. Low-vault and prone parsing are unchanged.

Output is `FRESH_WORK_DIR/delivery`, including the executable, cfg, base packs, all referenced optional packs, existing UI/themes/maps/docs/licenses and a build provenance summary. GitHub Actions publishes `rust-duty-onehand-windows-game-RUN-ATTEMPT`. Neither successful compilation nor successful packaging claims a gameplay capture or artistic review.

If a base pack needs fresh production, the explicit `--generate-base --blender BLENDER_EXE` option uses the ordinary export/import/merge plan without numerical parity. It is not part of the default existing-byte route. The separate `export_onehand.py` supports explicit approved-source replay/export when needed; old proof runners remain historical only.
