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
