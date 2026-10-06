# Fresh notebook launcher and bounded evidence preservation

Do not run an old notebook's cells or use Run all. Use new cells in the already verified private isolation notebook for this separately authorized task; no new notebook or account is needed. No allocation is performed by these source files. The coordinator publishes the proposal; only then substitute its exact 40-character support commit.

## Start one reviewed task

`notebooks/BOOTSTRAP_FILES.json` lists the exact five import-file SHA-256 values. `notebooks/public_a100_launcher.py` is a self-contained template with the same literal pins. It downloads only those public immutable-commit paths, verifies every file before any import/launch, invokes `/usr/bin/python3.12`, and detaches the controller into a fresh launch directory/log. Its default run installs the already authorized official distro dependencies, including X11 tools. It never imports an old notebook namespace or calls the old CPU frontend.

Record the actual allocation start outside the worker as soon as the newly authorized A100 runtime is allocated. Do not reset this timestamp when preparation begins. In new cells of that notebook, load/paste only the reviewed launcher definitions, then execute:

```python
SUPPORT_COMMIT = "<newly published immutable 40-character commit>"
ALLOCATION_START_UNIX = <actual observed allocation start, Unix seconds>
DEADLINE_UNIX = ALLOCATION_START_UNIX + 1800
launch_receipt = launch(SUPPORT_COMMIT, ALLOCATION_START_UNIX, DEADLINE_UNIX)
print(launch_receipt)
```

`poll(launch_receipt["launch_root"])` reads the detached controller's current result and process identity. Keep `controller.log` available; poll does not launch anything. If the controller exits, preserve evidence and disconnect immediately; do not wait for the deadline. The actual fresh run root is returned by poll once created. If launch fails before that, preserve controller.log and disconnect. Do not start a second instance to recover a failed first instance within this allocation.

## Preserve raw evidence before disconnect

First try the supported evidence-only file download once if useful. Save these three files: `a100-evidence-only.tar.gz`, `EVIDENCE_EXPORT_RECEIPT.json`, and final `RESULT.json`. A requested download without a captured/materialized file is not a successful transfer. The observed CPU proof's download controls returned no captured event, so keep the text fallback ready. Do not spend the allocation trying to download the optional executable.

For the fallback, import the already hash-verified helper from the launch tools directory in the same private notebook:

```python
import sys
from pathlib import Path
from IPython.display import display
sys.path.insert(0, str(Path(launch_receipt["launch_root"]) / "tools"))
import prepare_a100_text_export as tx
RUN_ROOT = Path("<fresh run_root reported by poll>")
def show_one(line):
    display({"text/plain": line}, raw=True)
index_report = tx.emit_index(RUN_ROOT, emit=show_one)
```

This emits only the manifest. Independently read its saved notebook output. Compute SHA-256 over the exact UTF-8 JSON bytes after the `A100_EVIDENCE_MANIFEST ` marker (exclude the marker, separating space and trailing newline), and compare it with `index_report["manifest_sha256"]`. Retain that observed digest for subsequent requests. The manifest lists every chunk index and SHA-256. Acknowledge that output before requesting data.

For each chunk, create a separate new notebook cell and explicitly request exactly one index. Never loop over all chunks, repeatedly overwrite one cell's output, or dump an 8 MiB payload into one browser transfer. For index 0, the previous acknowledged index is -1:

```python
chunk_report = tx.emit_chunk(
    RUN_ROOT,
    index=0,
    manifest_sha256="<independently observed manifest SHA-256>",
    chunk_sha256="<chunk 0 SHA-256 from that manifest>",
    acknowledged_through=-1,
    emit=show_one,
)
```

Before requesting index 1 in another new cell, verify index 0's output is complete, has the expected export ID and digest, and remains present in the notebook; then pass `acknowledged_through=0`. Continue one explicitly requested index at a time. Each decoded chunk is at most 48 KiB (64 KiB base64). An 8 MiB archive needs 171 requests. Emission is refused when fewer than 15 seconds remain on either the original monotonic or wall-clock deadline, or the host boot changed. A saved function return value alone is not evidence that a notebook output persisted.

After every chunk is independently acknowledged, use one additional new cell:

```python
end_report = tx.emit_finish(
    RUN_ROOT,
    manifest_sha256="<same independently observed manifest SHA-256>",
    acknowledged_through=<last verified chunk index>,
    emit=show_one,
)
```

Verify the END digest and all distinct chunk outputs are present, and verify the private notebook is saved using the notebook's normal save state/control. Then disconnect and delete the Colab runtime immediately. Do not wait to copy all base64 into the assistant's workspace while the GPU is still allocated. This recipe does not claim notebook persistence or shutdown until those browser observations succeed.

If the 8 MiB bound, per-call timeout, missing output or remaining allocation budget prevents complete preservation, do not remove raw frame/CSV/GPU data to shrink the result or mark the transfer successful. Preserve whatever valid receipts/logs are available, disclose the incomplete transfer and disconnect by the deadline. No new recipient, API, credentials, or external upload is used by this route.

## Reconstruct after GPU shutdown

Read the saved notebook outputs through read-only DOM access after the browser has verified shutdown. Save the exact `A100_EVIDENCE_MANIFEST`, each distinct `A100_EVIDENCE_CHUNK`, and `A100_EVIDENCE_END` line in a local UTF-8 transcript; avoid duplicate copies of rerendered output. Then use the same reviewed helper on the local CPU workspace:

```text
python3 prepare_a100_text_export.py materialize --transcript saved-notebook-text.txt --manifest-sha256 <independently observed digest> --output fresh-evidence-directory
```

Materialization rejects missing, duplicate, mixed, corrupted, truncated and oversized chunks; it verifies the original archive's exact byte count/SHA-256 and final result/receipt binding before creating the fresh output directory. It writes the archive, authoritative FINAL_RESULT.json, EVIDENCE_EXPORT_RECEIPT.json and a local materialization receipt. It does not extract or execute archive contents, and it does not independently prove GPU shutdown.
