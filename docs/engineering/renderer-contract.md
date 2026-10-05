# Native DX12 renderer contract fixture

`examples/renderer_contract.rs` exercises the real backend-neutral `DrawList`
through `WgpuRenderer`, reads the resulting PNG bytes back, and compares them
with fixed independent expectations. It uses original colored quads and the
embedded licensed text font. It does not load private soldier assets or advance
simulation, gameplay, input, or time.

## Windows invocation

Use a fresh or empty output directory:

```powershell
cargo run --locked --no-default-features --features wgpu-runtime --example renderer_contract -- --renderer=dx12 --force-fallback-adapter --output-dir evidence/renderer-dx12
```

`--force-fallback-adapter` is passed directly to `WgpuRenderer::new_headless` to
request a software adapter, normally WARP on Windows. The fixture records the
returned adapter name rather than inventing or assuming one. Omit this flag for
a hardware-first DX12 run. In either mode the returned `BackendInfo` must have
`requested == "dx12"`, `backend == "Dx12"`, and a nonempty adapter name.

Only explicit `--renderer=dx12` is accepted; there is no automatic selection,
Vulkan/Metal/GL substitution, or unavailable-adapter skip. Non-Windows execution
returns a clear nonzero error before creating its output directory. A build
without `wgpu-runtime` also returns a clear nonzero error. Compilation and CPU
helper tests on another platform are not native DX12 evidence.

Output directories must be empty to prevent a previous successful report or
capture from being reused after a failing run. The fixture never deletes old
evidence. Unknown flags, repeated options, missing values, filesystem failures,
GPU validation errors, readback failures, and mismatching pixels fail the run.
The renderer's readback wait is bounded to 30 seconds, followed by its bounded
mapping callback wait. CI should retain its own overall process timeout.

## Captured assertions

Every successful capture is decoded as PNG, required to have its exact RGBA8
extent, and checked for nonempty RGB coverage with a finite fraction in `(0,1]`.
All main-target captures require alpha 255 in every pixel. Probe checks use a
per-channel tolerance of 8 and require at least 90% matching pixels within each
inset; they do not pass an entirely wrong region on a whole-frame average.

| Captures | Independent contract |
| --- | --- |
| `quadrant.png` (96 x 64) | Red top-left, green top-right, blue bottom-left, yellow bottom-right. Each quadrant is probed with normalized inset `[.1,.4)` or `[.6,.9)` on each axis. This catches vertical flips and swapped channels/regions. |
| `readback-width-65.png` (65 x 49) | The same four probes with a 260-byte unpadded row that requires a 512-byte GPU copy stride. PNG rows must have their padding removed without changing orientation. |
| `quadrant-target.png` (96 x 64) | Draw the four asymmetric colored quadrants into a named offscreen target and capture its raw RGBA8 bytes. Fixed top-left red, top-right green, bottom-left blue, and bottom-right yellow probes independently check target drawing and readback orientation. |
| `quadrant-target-composite.png` (96 x 64) | Sample that same unchanged target into the main target over opaque black through `DrawList::draw_texture`, without UV compensation. The same four fixed probes independently check the target-to-composite sampling orientation. |
| `ordered-a-red.png`, `ordered-b-green.png` | One submission draws red, captures A, draws green, and captures B. A must remain red and B must be green. Returned capture paths must retain list order. |
| `depth-main-near.png` | A nearer red mesh occludes a later farther green mesh. |
| `depth-target-near.png`, `depth-target-reset.png` | Switching to a named depth target selects its storage; clearing that target clears its depth so a farther yellow mesh can replace earlier blue geometry. |
| `depth-main-preserved.png`, `depth-main-reset.png` | Clearing the named target does not erase the main target or its depth. Clearing the main target then resets its own depth. |
| `depth-disabled.png` | Returning to a 2D camera disables depth rejection. |
| `alpha-target.png` | Raw target bytes preserve half-alpha white, zero-coverage red emission, and an untouched transparent region. |
| `alpha-main-display.png` | Main PNG capture preserves sampled white/emission RGB and makes all alpha opaque even when the main target was transparent. |
| `alpha-composite.png` | Compositing the target over opaque black produces approximately 127 gray for half-alpha white and visible red emission. |
| `alpha-tinted-composite.png` | Target tint RGB and opacity attenuate associated RGB exactly once. |
| `alpha-clear.png` | A straight white clear with alpha .5 stores associated RGBA, approximately `[128,128,128,128]`. |
| `alpha-opaque-source.png` | Opaque replacement of a straight half-alpha white source stores associated RGBA, approximately `[127,127,127,127]`. |
| `text-100-percent.png`, `text-200-percent.png` | `Ag` at 16/32 physical pixels has fixed 1x/2x raster bounds; `Ag ` has fixed measured dimensions `[21,11,8]` and `[42,22,16]` (width, height, baseline offset). This checks raster dimensions, not font-style equivalence or native OS DPI event handling. |
| `after-errors.png` | A valid green capture still succeeds after invalid capture paths and a non-finite mesh are rejected. |

The two named-target quadrant captures share `orientation_group:
"named-target-to-main"` in their `extra` metadata, with `stage: "raw-target"`
and `stage: "sampled-main"` respectively. Each PNG is checked against independent
color constants, not against the other PNG, so matching flips in both captures
cannot pass. This covers a vertical sampling flip that the existing alpha bands,
whose colors do not vary vertically, cannot discriminate. It remains headless
target sampling evidence, not proof of window/swapchain presentation.

Negative native cases require failure for a PNG parent that is a regular file,
a PNG filename that is a directory, an empty capture path, and a mesh containing
NaN. The first two verify real readback/filesystem errors, rather than merely
reimplementing renderer path validation. Those intentional blocking paths remain
in the evidence directory. Unexpected acceptance or the wrong failure category
fails the whole fixture.

## Alpha and PNG representation

The internal render-target contract is **associated RGB plus optional additive
emission, with coverage in alpha**. This is a rendering correctness contract,
not a claim of historical legacy-pixel parity.

Explicit named-target captures retain those exact raw bytes for diagnostics:

- Half-alpha white uses vertex alpha 127 after the public `Color -> u8`
  conversion: approximately `[127,127,127,127]`.
- A half-strength additive red mesh over transparent storage contributes
  approximately `[127,0,0,0]`. Its RGB is emission; zero coverage must not erase it.
- Target sampling with tint RGB `(.5,.25,1)` and opacity `.5` yields white-region
  RGB approximately `[32,16,63]` and emission-region RGB `[32,0,0]`. These expected
  constants are independent of the renderer shader.

These PNGs are labeled `diagnostic_raw_target: true` and
`alpha_representation: "raw-associated-emissive-rgba8"`. They are **not reusable
straight-alpha artwork**: an ordinary image viewer may hide zero-alpha emission
or interpret associated RGB incorrectly. Do not unassociate them because that
would destroy meaningful zero-coverage emission.

Main captures (`Capture { target: None, .. }`) preserve stored RGB and set alpha
to 255, displaying the image over black. They use
`alpha_representation: "opaque-rgba8-rgb-preserved-over-black"` and
`diagnostic_raw_target: false`. This avoids multiplying coverage into the RGB a
second time and preserves emission. All PNGs are top-left-row-first RGBA8.

## Evidence files and success condition

Each of the 21 successful PNGs gets a primary `<filename>.png.json` sidecar with:

- Requested renderer, actual backend, and actual adapter, both at the top level
  and inside a `renderer` object
- Fixture case, filename, fallback-request flag, dimensions, and row origin
- Explicit alpha representation and raw-target diagnostic flag
- Observed nonblack coverage, independent expected probe colors and bounds,
  matching counts, tolerance, and required match fraction
- Case-specific details such as text raster dimensions or ordered checkpoint

The fixture writes `renderer-contract-report.json` only after every required
capture, pixel assertion, expected error, recovery capture, and sidecar write
has succeeded. Its `status: "passed"` and `native_execution: true` are meaningful
only with a zero process exit status from that run. The report records actual
backend/adapter, build identity, capture metadata, and expected error messages.
No success report is generated for missing GPU support or CPU-only tests.
The fixture does not change gameplay/time capture sidecars or upload anything.

This is headless renderer evidence. It does not establish window presentation,
resize/minimize behavior, native DPI handling, gameplay equivalence, performance,
or visual/artistic approval.

## CPU verification

On any supported build platform:

```sh
cargo check --locked --no-default-features --features wgpu-runtime --example renderer_contract
cargo test --locked --no-default-features --features wgpu-runtime --example renderer_contract
cargo clippy --locked --no-default-features --features wgpu-runtime --example renderer_contract -- -D warnings
```

Helper tests exercise the actual CLI parser and image probes, including valid
controls and discriminating vertical-flip, channel-swap, double-alpha,
lost-emission, tint-opacity, threshold, invalid-size, malformed-image, stale
output-directory, and filesystem failures. Expected colors are fixed in the
fixture, not read from shader source or generated from captures under test.
An additional CPU test inspects the actual named-target quadrant draw list: four
fixed colored meshes are followed by a raw capture, a switch to the main target,
and sampling of the same unchanged target before its main capture. This checks
fixture wiring only; the pixel probes still need a native DX12 run.
On non-Windows, an additional test verifies that native execution fails without
producing an output directory.

Follow the [engineering guide](../ENGINEERING_PRACTICES.md) when reporting results:
record the tested revision and commands, and keep CPU passed / native not run /
native passed or failed outcomes separate. Native DX12/WARP execution must occur
on Windows before describing this fixture as a genuine DX12 pass.

## Explicit screen-space target scaling

`draw::facade::set_screen_camera(target, logical_scale)` selects a 2D canvas
whose draw coordinates and text raster size use the supplied finite positive
logical-to-pixel scale. It does not change the platform's logical viewport or
reported OS DPI. The default remains unchanged: main-target UI uses window DPI,
and ordinary named targets use their own pixels. Perspective/default camera
selection and a new frame reset the explicit override. Named-target feedback
sampling remains forbidden. This additive facade helper changes no `Renderer`
trait or backend command format; fixtures can use actual UI draw paths at 1x/2x
without claiming that an OS DPI transition was exercised.
