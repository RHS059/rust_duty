# Bounded owned-process adapter v2

Original, standard-library source-only transport for the Rust Duty Windows proof.
It is a separate deliverable from `windows-proof-preparation-v1`. No frozen
producer, numerical algorithm, asset, native executable or existing receipt was
edited. **Actual Windows execution is unverified.** Linux synthetic tests and
mocked Win32 tests are not Windows-native or animation-proof evidence.

## v2 lifecycle corrections and review status

v1 is explicitly blocked by the independent review. Its package and review
artifacts remain unchanged. This separate v2 fixes the reproduced cases, but
**v2 independent acceptance and actual Windows execution remain unverified**.

- F1: drain cancellation is an explicit incomplete-stream failure. Both public
  consumption modes and terminal sealing require genuine stdout AND stderr EOF,
  no truncation, equal observed/retained byte counts/hashes, and verified cleanup.
  A canceled reader cannot turn a partial attempt into completed evidence.
- F2: every acquired Windows handle is tracked through constructor failure.
  Created-child ownership transfers before startup-attribute cleanup. Parent
  writer/NUL/thread close errors cannot escape cleanup. Independent closes are
  all attempted; uncertain handles are not blindly closed again. Failed launch
  exceptions carry actual PID, launch state, job-empty observation and cleanup
  outcome back to Running. Unverified cleanup retains both ownership locks and
  strong references to the remaining owned state. This is an inspection stop,
  not an automatic recovery/retry route.
- F3: the pipe object owns pending OVERLAPPED/buffer storage across exceptions.
  Failed waits request cancellation and observe completion through the API.
  Cancellation alone is insufficient. If completion cannot be established in a
  bounded grace, storage and handles are quarantined rather than freed/closed;
  incomplete cleanup propagates to the supervisor and keeps its ownership lock.
- F4: this package's `.gitattributes` applies `* -text` only below this directory.
  The local Git fixture checks identical source/index/checkout hashes with
  core.autocrlf=true and core.eol=crlf, including indexed attributes absent from
  the working tree. This is Linux fixture evidence, not an actual Windows
  checkout. Windows smoke still runs `--verify-pins` against the frozen bytes.

The exact review cases and neighboring lifecycle failures are in
`test_lifecycle_regressions.py`; `test_checkout_bytes.py` verifies the checkout
policy. Tests that intentionally retain a lock dispose only their mock-owned
fixture state afterward. Production code exposes no lock-reset API.
`minimal-changes.patch` records the source/test/documentation changes from v1.
Resource limits, direct-child RSS scope, public HostBinding/run/verifier
interfaces and numerical boundaries are unchanged.

## Public interface

```python
from owned_process import HostBinding, Limits, OwnedProcess, verify_attempt
binding = HostBinding(**proof_context.process_binding(explicit_environment))
with OwnedProcess.run(exact_argv, absolute_cwd, Limits(), fresh_output_root, binding) as attempt:
    for row in attempt.jsonl():
        unchanged_numeric_checker(row)
receipt = verify_attempt(fresh_output_root, require_completed=True)
```

For non-JSONL logs use `Limits(stdout_mode="bytes")`, then `attempt.wait()` within
the context. The attempt is single-use. A normal exit requires consuming the
iterator to exhaustion, or `wait()` in bytes mode; stopping early is partial.
Consumer exceptions propagate after owned-tree cleanup and receipt sealing.
All executable arguments remain exact strings, with no shell, PATH lookup,
automatic retry, output replacement, or process-name killing.

`HostBinding` requires `runner_id`, `run_id`, `build_sha256`, `context_sha256`,
`expected_host`, `environment`, and `owner_lock`. Both digests are lowercase
SHA-256 strings. `expected_host` must exactly equal `observed_host()`'s
system/release/version/machine observation. Environment values are passed only
to the child; receipts contain their canonical digest and key names, not their
values. The binding is copied before execution to prevent later caller mutation.
The context's `ProofContext.context_sha256` binds candidate, session, lineage,
role paths and file pins. The process adapter does not validate that provenance
by merely accepting a digest. The typed context and caller still admit it.

Use the **same dedicated owner-lock path for all stages sharing the native
resource slot**. Its parent must exist and its path must be outside the new
attempt directory. No preexisting lock is adopted or stolen. A process-wide
nonblocking serialization lock also prevents concurrent adapter contexts. A
changed lock is left untouched and makes the attempt fail. An incomplete kernel
cleanup keeps the lock, requiring explicit inspection rather than blind retry.
The filesystem is a trusted evidence directory; this is not an adversarial
filesystem sandbox or an atomic compare-and-unlink facility against a hostile
actor concurrently renaming parent directories.

## Fixed and bounded resources

Defaults retain the original 3 GiB **direct own-child sampled RSS/working-set**
ceiling, initial available physical memory of 3 GiB + 512 MiB, 1 GiB disk floor,
0.2-second observation interval, and 1,800-second stage deadline. Limits can be
tightened; these ceilings/floors cannot be relaxed. Tests use faster sampling,
shorter deadlines, very small streams, and at least 1.2 GiB disk free.

- Stdout: 256 MiB default total; explicitly bounded to at most 1 GiB.
- Stderr: 16 KiB default total; explicitly bounded to at most 1 MiB. Overflow is
  a failed stage, not silent truncation relabelled as complete.
- JSONL row and unfinished row: 16 MiB including newline, no relaxation.
- Queue: at most 2 rows and 32 MiB by default; hard configurable maxima 64 rows
  and 64 MiB. A blocked queue is a failure after 2 seconds by default (max 5).
- At most 100,000 JSON rows by default, hard configurable maximum 1,000,000.
- Each receipt: 256 KiB by default, 1 MiB hard maximum. Command, environment and
  metadata bounds reserve enough space for a final record.
- Samples: separate 4 MiB JSONL default, hard maximum 8 MiB; 10,000 observations
  by default. Count capacity must cover the entire deadline. No growing sample
  array is kept in memory or embedded in the terminal receipt.
- Read buffers: 64 KiB per pipe. Two reader threads and one independent monitor
  thread; one bounded raw-line queue. Decoding is one bounded row at a time.
  Python object expansion has a larger constant factor than raw row bytes.
- Before launch, free disk must cover the configured disk floor plus all maximum
  retained stream/sample/receipt bytes. Output writes and sample records are
  bounded. Candidate/Blender side-output capacity must be checked by the caller.

The monitor continues even if the consumer stops reading or throws. Every
resource observation is mandatory; missing/invalid live memory or disk data
fails closed. RSS is **sampled**, not a guaranteed instantaneous peak, aggregate
tree memory, private-byte allocation or committed-memory limit. Physical memory
availability is not a cgroup/container memory-limit observation. Scheduling or
filesystem delays can delay a sample; sample timestamps expose actual cadence.

The deadline uses `time.monotonic()`, independently of wall-clock changes, and
includes adapter preparation before child launch. It bounds the child stage,
not arbitrary checker computation after the child has exited. The independent
monitor stops the launched process even when the caller is blocked. A bounded
cleanup grace follows; a stuck kernel I/O operation cannot be declared successful.

## Windows lifetime and transport

Requires 64-bit Python and Windows 10 / Server 2016 or later. Unsupported APIs or
failed job assignment are terminal failures, with **no fallback to uncontained
launch or breakaway from an ancestor job**.

1. Create one unnamed, non-inheritable Job Object with
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and without breakaway flags.
2. Create private, remote-rejecting named pipes. Only the three child standard
   handles are in `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`; the job handle is not.
3. Launch with `CreateProcessW`, explicit executable, mutable correctly quoted
   command line and explicit Unicode environment. The startup attribute
   `PROC_THREAD_ATTRIBUTE_JOB_LIST` assigns the child to our job **before its
   first thread can execute**. There is no separate suspended-then-assign gap.
4. Verify membership. If the hosting runner is already in a job, use normal
   supported nested membership; if the atomic creation is rejected, fail closed.
   No ancestor job is terminated. An unexpected membership-check failure stops
   only the newly created process handle and our own job.
5. Reader threads use overlapped `ReadFile`, events, `GetOverlappedResult` and
   `CancelIoEx`. There is no `/proc`, `killpg`, selector-on-pipe assumption,
   `PeekNamedPipe` synchronous-blocking shortcut, Popen private handle or shell.
   The OVERLAPPED and buffer remain live through cancellation completion.
6. At root exit or violation, terminate only our job, preserve the root's exact
   unsigned Windows exit code, and require job accounting ActiveProcesses == 0.
   All descendants remain contained because breakaway is not enabled. The last
   job handle is closed on cleanup and also provides process-crash containment.
   On termination API failure, owned kill-on-close is attempted; success is not
   claimed and the owner lock remains for inspection.

The Windows implementation has mocked regression evidence and awaits v2 independent acceptance; it is **not yet exercised
against a Windows kernel**. The guarded smoke tests must pass on the selected
runner before it becomes a production dependency. They check a descendant's
actual process handle is signalled and an unrelated Python process survives.
Runner cancellation/crash containment still needs a selected-runner integration
exercise; successful child-timeout tests alone do not demonstrate that case.

## Linux behavior and boundaries

Linux uses an explicitly owned new session/process group, nonblocking pipe
readers and `/proc` observations. `waitid(WNOWAIT)` retains the original root PID
until group termination, avoiding a post-reap process-group-ID reuse window.
Only that owned group is signalled, including when the root exits before a child.
This supports the current cooperative Blender/sampler launch model. It is not
containment for a malicious Linux descendant that deliberately calls `setsid()`
or migrates to another session; use an admitted cgroup/container supervisor for
that threat model. macOS and other unimplemented platforms fail closed.

## Receipts and retained failures

Every accepted attempt gets a fresh exclusive directory. Files are exclusively
created and never overwritten:

- `attempt.json`: durable prepared record before launching anything.
- `started.json`: exact argv/cwd, host/build/context, executable identity, PID,
  backend and initial resource observations after successful launch.
- `stdout.bin`, `stderr.bin`: exact retained bytes, including malformed/partial
  output. Total observed byte hashes/counts and retained prefix hashes/counts are
  separate. Unread bytes after termination are never claimed as captured.
- `samples.jsonl`: bounded independently hashed memory/disk/time observations.
- `transport.json`: durable child/transport termination even if the consumer has
  not yet exited its context. It deliberately cannot claim completed proof.
- `terminal.json`: final completed / failed / partial state, code/signal/timeout,
  reason, consumer status, cleanup status, identities, byte hashes and counts,
  sampled peak and sample count. Failure before launch is `failed`; interrupted
  consumption or incomplete stream retention is `partial`.
- `terminal.sha256.json`: byte identity of the terminal record. All metadata
  records bind their predecessors. These hashes detect changes relative to a
  trusted expected hash; they are not signatures or independently trusted proof.

Writes flush and fsync. Linux also fsyncs receipt directories. Python maps fsync
to the platform mechanism on Windows; machine loss, disk failure or termination
between writes can leave only earlier durable files. Missing terminal records,
missing seals, live readers, or write failures mean incomplete evidence, never
success. A terminal receipt cannot be promised against physical storage failure.
The pre/post executable fingerprint binds path, bytes, hash, inode/device and
mtime; it detects ordinary replacement but is not an OS loaded-image attestation
or a defence against hostile replace-and-restore races. The production context
must select a trusted immutable tool bundle.

`verify_attempt()` checks bounded local filenames, receipt-chain and stream
hashes/sizes, schema/limits and internally consistent completion. With
`require_completed=True` it rejects partial or failed attempts. It does not
admit the source/candidate, validate mathematical rows, or authenticate the
caller-supplied context/build digests.

## Exact integration boundary

Only new versioned callers may use this module. The following source files were
read and hashed, and must remain unchanged in this revision:

- `onehand-runtime-20261016-r2/native-window-v2/run_window.py`:
  replace resource/transport equivalents of `mem_available`, `child_rss` and
  `run_monitored`. Its `native_commands`, source flags, numerical checks and
  source/Blender pin validation stay outside this adapter.
- `.../runtime-parity/verify_onehand_r2.py`: replace `probe`'s Linux pipe selector,
  sampling and process lifecycle. Feed `attempt.jsonl()` directly to unchanged
  Checker/FrozenMap/geometry comparison code. No row schema, tolerances, sample
  grid, SOURCE_SHA or aggregate coverage changes belong here.
- `.../runtime-parity/serial_r2.py`: replace only `Runner.process`'s spawn/wait/
  disk/deadline transport. Keep stage ordering, validators, candidate/session
  pins, durable stage records and retirement authorization unchanged.

These are **not monkey patches or drop-in legacy receipt rewrites**. New process
receipts use a versioned schema. Legacy adapters can map command, exit_code,
completed, timed_out, signal, resource_stop_reason and sampled peak explicitly,
but must reference the bounded sample file instead of pretending it is an old
unbounded `memory_samples` list. `stdout.bin` and `stderr.bin` are separately
hashed; never concatenate them and claim the old merged interleaving. A caller
that expects pure JSON stdout must select stdout explicitly and retain stderr
as diagnostics. Preserve exact existing native command arguments.

Important: the 3 GiB ceiling observes the **direct launched child**. Launch
Blender and the sampler directly from the new coordinator when that bound must
apply to them. Wrapping a Python launcher and reporting its RSS as Blender RSS
is invalid. Do not nest two adapter contexts with the same owner lock. An outer
stage wrapper topology must be revised explicitly or use independently admitted
leaf supervision; no hidden lock bypass is included.

`DEPENDENCIES.json` pins the inspected old boundaries and preparation contracts.
`ProofContext.process_binding(environment)` in the separately owned candidate
context package supplies the compatible binding dictionary. No imports from
that package, copied geometry, numerical source edits or monkey-patched identity
constants are part of this adapter.

## Tests and next Windows gate

Run locally with an installed Python, without installing anything:

```text
python -B -m unittest discover -s onehand-runtime-20261016/windows-process-adapter-v2 -p "test_*.py" -v
```

`run_tests.py --verify-pins --summary <fresh-file>` produces a bounded machine
summary. `--require-windows` refuses Linux immediately. The four native Windows
tests are explicitly skipped on Linux; their absence never becomes a Windows
pass. `OWNED_ADAPTER_EVIDENCE_ROOT` retains only the original Windows Python-test
receipts. It is not a private asset ingestion path.

`windows-process-smoke.workflow.yml` is an **uninstalled, undispatched proposal**
for `.github/workflows/windows-process-smoke.yml` in the next authorized source
revision. It uses read-only repository permissions, sparse source checkout, the
runner's installed Python, no package installation, no secrets, no Blender/game/
asset downloads, and a bounded 8-minute Windows job. It uploads only synthetic
smoke receipts to the same workflow's artifact service. This is an explicit
future evidence-retention step, not an action performed while writing this
package. Paths must match the source-only revision before enabling it.

Passing that smoke would validate the small process transport, **not actual
animation assets, source reproduction, Blender compatibility, 67-chunk runtime
parity, GL/DX12 behavior, input delivery or screenshots**. Those remain separate
production gates. Do not dispatch the larger proof merely because this smoke is
green. Selected-runner job nesting, cancellation, storage durability, actual
Blender/sampler working-set behavior and full host/build provenance remain to be
verified on the target.

## Primary references consulted

- [Microsoft: atomic Job Object assignment and the suspended-process orphan gap](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812/)
- [Microsoft: JOB_LIST and HANDLE_LIST startup attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Microsoft: Job Objects and kill-on-close](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Microsoft: TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)
- [Microsoft: GetProcessMemoryInfo](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo)
- [Microsoft: GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
- [Microsoft: overlapped ReadFile buffer/result rules](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile)
- [Microsoft: CancelIoEx and pending-buffer lifetime](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex)
- [Microsoft: named pipe client connection](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-client)
- [Python: subprocess and Windows command-line conversion](https://docs.python.org/3/library/subprocess.html)
- [Python: waitid/WNOWAIT and fsync](https://docs.python.org/3/library/os.html)
- [Pinned checkout v4.2.2 source](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683)
- [Pinned upload-artifact v4.6.2 source](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02)
