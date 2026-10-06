# Bounded Windows real-game matrix caller

`performance-matrix-feedback.yml` runs one native DX12 WARP smoke and, only after
complete valid smoke analysis, five sequential pilot processes: 1080p baseline,
720p, 1440p, 1080p ADS, 1080p baseline. Each process gets 10 seconds warmup and
30 seconds recording. Physical surface extent, focus, input, paired CPU stages,
process isolation and CPU adapter classification remain mandatory. A setup or
trace failure stops execution. It is CPU software diagnostic evidence; it cannot
establish the RTX 3080 Ti 1080p60 goal or full-matrix completion.

The caller runs only on main pushes touching its runner/reader/caller files, on
one separate Windows runner, with a distinct non-cancelling concurrency group.
There is no manual dispatch, build, capture-suite rerender, deployment or release.
The only downloaded package is artifact 11432281909 from run 37505927104 attempt
1, source `49c3bf9b3d0482ce81a7d50683904bda28468d7d`. Exact repository IDs,
run/attempt/source, artifact ID/name/size/digest and expiry are checked before
retrieval. Expiry or identity mismatch fails closed; it does not choose a newer
or similarly named package. The supported download action extracts the package
and fails on a digest mismatch. See [GitHub's download action](https://github.com/actions/download-artifact).

The runner checkout uses the triggering source revision. A separate source
checkout verifies the pinned package's runtime bytes. Receipts retain both
identities, runner source hashes/copies, executable and adjacent-file hashes,
package build metadata, Python/host identity, and actual per-trace adapter,
backend, driver, physical extent and DPI. The shader compiler and package build
command are retained; the original native compiler fingerprint is explicitly
unavailable because the package does not carry it. No current compiler is used
as a proxy. Upstream workflow status is retained without claiming its independent
quality/comparison lanes passed.

The seven-day evidence artifact retains raw game traces, gameplay/GPU exports,
per-process logs and receipts, plans, provider metadata, and an honest summary of
missing/failed cases. Its scope is at most six short game processes. The input
executable, package assets and archive are not uploaded again. The game runs only
on the existing desktop; refused focus/input or missing desktop support remains
a reported failure.

Local protocol checks (no game launch):

```sh
python -m unittest discover -s tools -p test_performance_matrix_workflow.py
python -m unittest discover -s tools -p test_performance_matrix.py
```
