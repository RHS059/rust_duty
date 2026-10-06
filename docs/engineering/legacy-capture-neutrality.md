# Legacy GL capture neutrality

A default-framebuffer capture must not change subsequent untextured rendering
within the same submission. This regression covers the production
`LegacyRenderer`, with original solid quads and no game assets.

## Defect and repair

Macroquad 0.4.14 `Texture2D::grab_screen()` binds its screenshot texture with raw
OpenGL calls. Miniquad 0.4.8 still caches the previous texture binding. When that
cached texture is the white fallback, a subsequent untextured mesh can skip its
necessary bind and sample the screenshot instead. Its vertex colors then become
modulated by unrelated world pixels.

The default-framebuffer capture branch invalidates Miniquad bindings immediately
after readback. In this pinned OpenGL implementation, `commit_frame()` clears
buffer and texture bindings; it does not present, clear targets, or advance the
application. Named-target readback and the returned screenshot pixels are
unchanged. Review this workaround if either pinned dependency changes.

## Native fixture

```sh
cargo run --locked --no-default-features --features legacy-macroquad \
  --example legacy_capture_contract -- --output-dir <fresh-directory>
```

The fixture creates a 256x256 native GL window and preallocates a depth target.
The explicit canvas is above the decorated Windows minimum client width, which
expanded an attempted 64x64 surface to 120x64 on the native runner.
It renders a gray control, then warm and cool world passes. Each world pass is
captured from the default framebuffer immediately before the same untextured
gray mesh is rendered into the existing target. No text, fresh target allocation,
or frame boundary can incidentally repair the cache between those commands.

Each of the 248x248 interior pixels must equal these fixed RGBA bytes, with no
channel tolerance:

- `baseline.png`: `[128,128,128,255]`
- `warm-world.png`: `[204,51,26,255]`
- `warm-after.png`: `[128,128,128,255]`
- `cool-world.png`: `[26,102,204,255]`
- `cool-after.png`: `[128,128,128,255]`

A pre-fix renderer fails the gray expectation because it samples the world
snapshot. A screenshot-modulated value is a failing control, never a new golden.
The checker tests reject that fault and a one-channel, one-unit interior error.

## Windows execution and retained evidence

The existing Windows GL job builds the fixture with the game and UI example,
then runs `tools/run_windows_gl_capture_contract.py` using the same pinned
app-local Mesa runtime. The wrapper reuses the established runtime staging,
bounded process execution, environment restoration, and process-receipt helpers.
It independently checks all five PNGs, report identity, exact capture order,
source revision, and executable immutability. Loaded-module verification is not
claimed.

The screenshot-neutrality run is independent of earlier UI/calibration outcomes
once its build and Mesa staging succeeded. Its captures, process logs, source
and executable identities, summary, and staging receipt are retained on success
or failure. The existing calibrated presentation gates and tolerances remain
unchanged.

Local checks:

```sh
cargo test --locked --no-default-features --features legacy-macroquad \
  --example legacy_capture_contract
PYTHONPATH=tools python -m unittest -v test_windows_gl_capture_contract \
  test_calibrated_feedback_workflow
```

A local compile or synthetic process test does not establish a Windows native
pass. Use that exact workflow attempt's process receipts and PNGs. This narrowly
scoped regression does not establish hardware performance, human visual approval,
or completion of other authored-animation or cross-backend acceptance gates.
