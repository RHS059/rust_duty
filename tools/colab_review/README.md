# Colab animation review

Open `Rust_Duty_Animation_Review.ipynb` in Google Colab with File → Upload notebook.
Select Runtime → Change runtime type → A100 GPU if available. Run the synthetic demo before supplying a ZIP. For CPU-only pack diagnostics, choose CPU rather than spending GPU compute units.

Set `DEMO=False`, upload one ZIP of authorized inputs, then set `PACK`, `CLIP`, `CHANNEL_KIND`, `CHANNEL_INDEX`, and optional explicit `TRANSITIONS`. Supported lowercase extensions: `.vra`, `.vrs`, `.vrm`, `.json`, `.png`, `.jpg`, `.jpeg`. No gzip, executables, private soldier assets, or automatic repository downloads. Matched optional companions use the same prefix. Input ZIP is never extracted.

The notebook contains its own frozen parser modules and a synthetic fixture. No repository checkout, Drive mount, credentials, model download, or Blender installation is required. Pinned direct dependencies: NumPy 2.3.5, Matplotlib 3.10.8, Pillow 12.3.0. Colab's existing PyTorch is optional; its actual version/device are reported rather than reinstalling a CUDA stack.

## Outputs and limits

- JSON provenance with SHA256 for every input and embedded module, versions, selected channels and explicit transitions.
- Parent-local bone / scene-global rigid translation and sampled-speed plots. glTF Y-up; runtime Ry(pi) not applied. Translation units are export units unless confirmed separately.
- Loop endpoint and selected unblended end-to-start gap measurements, including visibility changes. Speeds are sampled segment averages, with shortest-arc rotation aliasing possible. No universal pass/fail threshold or approval score.
- Optional companion structural/checksum/skeleton/assignment validation, **not** skin-deformation or inverse-bind parity proof.
- Optional named evaluated-world contact-point pairs in metres with explicit observability masks. Reports coverage and observed separation only, never anatomy, penetration, orientation or grasp approval. Schema example is in the notebook. World coordinates are bounded to ±10000 metres. Declared source hash is separately marked verified only if its bytes are supplied.
- Optional unwarped source/candidate still panels with explicit frame/PTS and sample time labels. No time mapping inferred, automatic registration, video similarity score or complete-clip approval.
- Optional CUDA point separation uses float64 and checks numerical equivalence to CPU (`rtol=1e-9`, `atol=1e-10`). Small arrays rarely justify GPU allocation. A100 is not needed for parsing or plots.

Download the result ZIP, then **Runtime → Disconnect and delete runtime**. No keepalive or unattended loop. [Official Colab FAQ](https://research.google.com/colaboratory/faq.html) explains changing hardware availability, runtime lifetime and output sharing. Omit sensitive cell outputs before sharing notebooks.

## Developer checks

From repository root:

```sh
PYTHONPATH=tools:tools/colab_review python3 -m unittest discover -s tools/colab_review/tests -v
python3 tools/colab_review/build_notebook.py
python3 tools/colab_review/smoke_notebook.py
```

The generator reads the repository's `tools/vrpack.py`, `vrskin.py`, and `vrview.py`; the delivered notebook freezes those exact source bytes. The smoke test stubs only Colab's download UI and skips the dependency installation cell; it executes real CPU analysis and ZIP writing.

Validation on 2026-10-04: Python 3.12.14, the pinned NumPy/Matplotlib/Pillow versions above; 16 focused tests pass. Synthetic notebook CPU execution through ZIP generation passes. Existing local repository ADS (47), reload (1), and directional (48) clips pass real parser+companion checks. Plot visually inspected. Original parsers retrieved from main based at `61c3ccd26e8cf9f288e5e56c536c92b7d30409ef`. No private assets are embedded or published. PyTorch/CUDA, A100 and actual Colab account session not executed; nbformat package unavailable locally, so no nbformat validator claim. No game binaries or runtime code changed; full game build intentionally not triggered.

All results remain `diagnostic`. Evaluated full-motion inspection, export/reimport parity and target-game runtime verification remain separate gates. No Blender preview or other render is performed by this tool.

## One-shot A100 batch lifecycle

Connect only when ready, then run a bounded task, preserve its output, and release the runtime. The optional `batch-cuda-smoke-v1` cell checks 4096 synthetic point pairs on the actual A100 against float64 CPU results. It defaults off; set `RUN_CUDA_SMOKE=True` for the short GPU verification batch. This is numerical pipeline evidence, not a real animation/contact approval or speed benchmark.

The export cell now records the ZIP SHA256 and an exact output snapshot. After the browser download completes, set `CONFIRM_TEARDOWN=True` in `batch-teardown-v1` and select that downloaded ZIP. It verifies identical bytes, archive content, and unchanged outputs before calling `runtime.unassign()`. Cancel/mismatch/error retains the runtime; fix preservation and retry instead of losing outputs. Do not use an unconditional finally/unassign, timed shutdown, or assume `files.download()` finished saving. This only guards this review's outputs; preserve other VM work separately.

Verify release outside the kernel: disconnected notebook AND removal from Runtime → Manage sessions. If its entry remains, use Runtime → Disconnect and delete runtime once preservation is confirmed. Do not reconnect just to verify; that can allocate a fresh instance. The API request does not itself prove billing has stopped or hardware deletion has finished.

[Official runtime implementation](https://github.com/googlecolab/colabtools/blob/main/google/colab/runtime.py) requests unassignment then disconnects. [Official download implementation](https://github.com/googlecolab/colabtools/blob/main/google/colab/files.py) initiates asynchronous browser transfer. Neither grants a durable browser-download acknowledgment to Python. This intentionally uses a saved-copy round trip, without Drive access grants or credentials.

Revision validation: 24 tests pass, including saved-copy mismatch, changed/new outputs, modified archive, nested output rejection, default no-teardown behavior and original cell-ID preservation. CPU notebook smoke still passes. No actual GPU or unassignment executed locally. Original `review-00` through `review-12` IDs are unchanged; added IDs are `batch-cuda-smoke-v1` and `batch-teardown-v1`.
