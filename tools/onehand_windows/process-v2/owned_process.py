"""Bounded owned-child transport. Original code; no numerical proof logic.

Usage: with OwnedProcess.run(argv, cwd, limits, output_root, binding) as run:
           for row in run.jsonl(): check(row)
A normal context exit is successful only after complete stream consumption.
Use stdout_mode='bytes' and run.wait() for a non-JSONL native log stage.
"""
from __future__ import annotations
from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import copy
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

GIB, MIB = 1024**3, 1024**2
SERIAL = threading.Lock()
INCOMPLETE_ATTEMPTS = []
HEX = re.compile(r'^[0-9a-f]{64}$')

class AdapterError(RuntimeError): pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def file_identity(path):
    path = Path(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise AdapterError('executable must be a regular file')
        sha = hashlib.sha256()
        while True:
            block = stream.read(MIB)
            if not block: break
            sha.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise AdapterError('executable changed while hashing')
    return {'path': str(path), 'sha256': sha.hexdigest(), 'bytes': after.st_size,
            'device': after.st_dev, 'inode': after.st_ino, 'mtime_ns': after.st_mtime_ns}


def observed_host():
    return {'system': platform.system(), 'release': platform.release(),
            'version': platform.version(), 'machine': platform.machine()}


@dataclass(frozen=True)
class Limits:
    rss_bytes: int = 3 * GIB
    initial_available_bytes: int = 3 * GIB + 512 * MIB
    disk_floor_bytes: int = GIB
    sample_seconds: float = 0.2
    deadline_seconds: float = 1800.0
    max_stdout_bytes: int = 256 * MIB
    max_stderr_bytes: int = 16384
    max_row_bytes: int = 16 * MIB  # Includes the newline; also bounds partial rows.
    max_rows: int = 100000
    queue_bytes: int = 32 * MIB
    queue_rows: int = 2
    queue_wait_seconds: float = 2.0
    max_receipt_bytes: int = 256 * 1024
    max_samples_bytes: int = 4 * MIB
    max_samples: int = 10000
    drain_seconds: float = 2.0
    stdout_mode: str = 'jsonl'

    def validate(self):
        upper = {'rss_bytes': 3*GIB, 'max_stdout_bytes': GIB, 'max_stderr_bytes': MIB,
                 'max_row_bytes': 16*MIB, 'max_rows': 1000000, 'queue_bytes': 64*MIB,
                 'queue_rows': 64, 'max_receipt_bytes': MIB, 'max_samples_bytes': 8*MIB,
                 'max_samples': 100000}
        for name, maximum in upper.items():
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= maximum:
                raise AdapterError('invalid/tightenable limit: ' + name)
        if type(self.initial_available_bytes) is not int or self.initial_available_bytes < 3*GIB+512*MIB:
            raise AdapterError('initial memory reserve may not be relaxed')
        if type(self.disk_floor_bytes) is not int or self.disk_floor_bytes < GIB:
            raise AdapterError('disk floor may not be relaxed')
        for name, maximum in (('sample_seconds', .2), ('deadline_seconds', 1800),
                              ('queue_wait_seconds', 5), ('drain_seconds', 5)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise AdapterError('invalid/tightenable duration: ' + name)
        if self.stdout_mode not in ('jsonl', 'bytes'):
            raise AdapterError('unknown stdout mode')
        if self.queue_bytes < self.max_row_bytes or self.max_receipt_bytes < 16384:
            raise AdapterError('queue must hold one row; receipt needs at least 16 KiB')
        if self.max_samples < math.ceil(self.deadline_seconds / self.sample_seconds) + 2:
            raise AdapterError('sample count cannot cover the entire deadline')
        return self

    @property
    def retained_budget(self):
        # attempt, started, transport, terminal, and terminal integrity sidecar.
        return self.max_stdout_bytes + self.max_stderr_bytes + self.max_samples_bytes + 5*self.max_receipt_bytes


@dataclass(frozen=True)
class HostBinding:
    runner_id: str
    run_id: str
    build_sha256: str
    expected_host: dict
    environment: dict
    owner_lock: str
    context_sha256: str

    def validate(self):
        for value in (self.runner_id, self.run_id):
            if not isinstance(value, str) or not 0 < len(value) <= 128 or '\0' in value:
                raise AdapterError('bounded runner/run IDs required')
        for name in ('build_sha256', 'context_sha256'):
            value = getattr(self, name)
            if not isinstance(value, str) or not HEX.fullmatch(value):
                raise AdapterError(name + ' requires a lowercase SHA-256')
        if self.expected_host != observed_host():
            raise AdapterError('host binding differs from actual host')
        if not isinstance(self.environment, dict) or len(self.environment) > 256:
            raise AdapterError('bounded explicit environment required')
        folded = set()
        for key, value in self.environment.items():
            if not isinstance(key, str) or not key or '=' in key or '\0' in key:
                raise AdapterError('invalid environment key')
            if not isinstance(value, str) or '\0' in value:
                raise AdapterError('invalid environment value')
            if key.upper() in folded:
                raise AdapterError('ambiguous case-folded environment key')
            folded.add(key.upper())
        if len(canonical(self.environment)) > 64*1024:
            raise AdapterError('environment too large')
        if os.name == 'nt' and not any(k.upper() == 'SYSTEMROOT' for k in self.environment):
            raise AdapterError('explicit Windows SystemRoot required')
        if not Path(self.owner_lock).is_absolute():
            raise AdapterError('absolute owner lock required')
        return self

    def record(self):
        return {'runner_id': self.runner_id, 'run_id': self.run_id, 'build_sha256': self.build_sha256,
                'context_sha256':self.context_sha256, 'observed_host': self.expected_host, 'environment_sha256': digest(self.environment),
                'environment_keys': sorted(self.environment), 'owner_lock': self.owner_lock}


class Resources:
    def __init__(self):
        if platform.system() not in ('Linux', 'Windows'):
            raise AdapterError('unsupported platform: fail closed')
        self.win = None
        if os.name == 'nt':
            from windows_job import WinAPI
            self.win = WinAPI()

    def available(self):
        if self.win: return self.win.available()
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) * 1024
        raise AdapterError('MemAvailable unavailable')

    def disk(self, path): return shutil.disk_usage(path).free


class LinuxPipe:
    def __init__(self, stream):
        self.stream = stream
        os.set_blocking(stream.fileno(), False)
    def read(self, count, cancel):
        while not cancel.is_set():
            try: return os.read(self.stream.fileno(), count)
            except BlockingIOError: cancel.wait(.02)
        return b''
    def close(self): self.stream.close()


class LinuxProcess:
    kind = 'linux-owned-session-v1'
    def __init__(self, argv, cwd, env):
        if platform.system() != 'Linux' or not hasattr(os, 'WNOWAIT'):
            raise AdapterError('Linux waitid/WNOWAIT required')
        self.child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, close_fds=True, bufsize=0)
        self.pid = self.child.pid
        self.stdout, self.stderr = LinuxPipe(self.child.stdout), LinuxPipe(self.child.stderr)
        self.reaped = False

    def poll(self):
        # Do not reap until group termination. The zombie leader reserves its PID,
        # so an unrelated process group cannot acquire the same number mid-cleanup.
        value = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if value is None: return None
        return value.si_status if value.si_code == os.CLD_EXITED else -value.si_status

    def rss(self):
        for line in Path(f'/proc/{self.pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'): return int(line.split()[1]) * 1024
        if self.poll() is not None: return None
        raise AdapterError('live child VmRSS unavailable')

    def stop_tree(self):
        if self.reaped: raise AdapterError('refuse signalling reaped/reusable process group')
        try: os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError: pass

    def reap(self):
        code = self.child.wait(timeout=5)
        self.reaped = True
        return code

    def close(self):
        self.stdout.close(); self.stderr.close()


def launch(argv, cwd, env):
    if platform.system() == 'Linux': return LinuxProcess(argv, cwd, env)
    if platform.system() == 'Windows':
        from windows_job import WindowsProcess
        return WindowsProcess(argv, cwd, env)
    raise AdapterError('unsupported platform: fail closed')


def safe_parent(path):
    """Reject symlinks/reparse points instead of normalizing past them."""
    path = Path(path)
    if not path.is_absolute() or any(part in ('.', '..') for part in path.parts):
        raise AdapterError('absolute normalized path required')
    for part in (path, *path.parents):
        if not part.exists() and not part.is_symlink(): continue
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise AdapterError('symlink/reparse path rejected: ' + str(part))
    if not path.parent.is_dir(): raise AdapterError('existing parent directory required')
    return path


def durable(path, value, maximum):
    data = canonical(value)
    if len(data) > maximum: raise AdapterError('receipt size exceeded')
    with Path(path).open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    if os.name != 'nt':
        fd = os.open(str(Path(path).parent), os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    return {'path': Path(path).name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class ByteQueue:
    def __init__(self, max_bytes, max_rows):
        self.max_bytes, self.max_rows = max_bytes, max_rows
        self.items = deque(); self.bytes = 0
        self.peak_bytes = self.peak_rows = 0
        self.cv = threading.Condition()
    def put(self, value, stop, seconds):
        end = time.monotonic() + seconds
        with self.cv:
            while self.bytes + len(value) > self.max_bytes or len(self.items) >= self.max_rows:
                remaining = end - time.monotonic()
                if remaining <= 0 or stop.is_set(): return False
                self.cv.wait(min(.02, remaining))
            if stop.is_set(): return False
            self.items.append(value); self.bytes += len(value)
            self.peak_bytes = max(self.peak_bytes, self.bytes); self.peak_rows = max(self.peak_rows, len(self.items))
            self.cv.notify_all()
            return True
    def get(self, done, stop):
        with self.cv:
            while not self.items:
                if done.is_set() or stop.is_set(): return None
                self.cv.wait(.02)
            value = self.items.popleft(); self.bytes -= len(value); self.cv.notify_all()
            return value


class StreamRecord:
    def __init__(self, path, maximum):
        self.path, self.maximum = Path(path), maximum
        self.stream = self.path.open('xb', buffering=0)
        self.hash = hashlib.sha256(); self.observed_hash = hashlib.sha256(); self.bytes = self.observed = 0
        self.eof = self.closed = self.truncated = False
    def add(self, block):
        self.observed += len(block); self.observed_hash.update(block)
        kept = block[:max(0, self.maximum - self.bytes)]
        if kept:
            view = memoryview(kept)
            while view:
                written = self.stream.write(view)
                if not written: raise OSError('short output write')
                self.hash.update(view[:written]); self.bytes += written; view = view[written:]
        if len(kept) != len(block):
            self.truncated = True
            raise AdapterError('output limit exceeded')
    def close(self):
        if not self.closed:
            self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close(); self.closed = True
    def record(self):
        return {'path': self.path.name, 'sha256': self.hash.hexdigest(), 'bytes': self.bytes,
                'observed_bytes': self.observed, 'observed_sha256': self.observed_hash.hexdigest(), 'eof_observed': self.eof,
                'truncated': self.truncated, 'scope': 'exact retained bytes; no claim about unread bytes'}


class OwnedProcess:
    @staticmethod
    def run(argv, cwd, limits, output_root, host_binding):
        return Running(argv, cwd, limits, output_root, host_binding)


class Running:
    def __init__(self, argv, cwd, limits, output_root, host_binding, *, resources=None, launcher=None):
        self.argv = list(argv) if isinstance(argv, (list, tuple)) else None
        self.cwd = str(cwd); self.limits = limits; self.output_root = Path(output_root); self.binding = host_binding
        self.resources, self.launcher = resources, launcher or launch
        self.process = None; self.receipt = None; self.reason = None; self.error = None
        self.cancel = threading.Event(); self.stop = threading.Event(); self.done = threading.Event()
        self.state_lock = threading.Lock(); self.streams = {}; self.readers = []
        self.started = False; self.entered = False; self.iterator_used = False; self.iterator_complete = False
        self.rows = 0; self.sample_count = 0; self.peak_rss = 0; self.exit_code = None
        self.supervisor_identity = None
        self.lock_data = self.lock_stat = None; self.serial_held = False; self.lock_held = False
        self.root_created = False; self.cleanup_complete = True
        self.executable_before = self.executable_after = None
        self.queue = None; self.monitor = None

    def fail(self, reason, exc=None):
        with self.state_lock:
            if self.reason is None:
                self.reason = reason
                # Do not serialize arbitrary exception text (paths/secrets/huge data).
                self.error = type(exc).__name__ if exc is not None else None
            self.stop.set()

    def __enter__(self):
        if self.entered: raise AdapterError('attempt contexts are single use')
        self.entered = True; self.t0 = time.monotonic(); self.started_unix = time.time()
        self.limits.validate(); self.binding.validate()
        self.binding = copy.deepcopy(self.binding)
        if not self.argv or len(self.argv)>1024 or any(not isinstance(v,str) or '\0' in v for v in self.argv):
            raise AdapterError('explicit bounded argv list of strings required')
        if len(canonical(self.argv)) > 32768 or not Path(self.argv[0]).is_absolute():
            raise AdapterError('absolute executable and at most 32 KiB argv required')
        if not Path(self.cwd).is_absolute() or not Path(self.cwd).is_dir():
            raise AdapterError('existing absolute cwd required')
        self.output_root = safe_parent(self.output_root)
        self.lock_path = safe_parent(self.binding.owner_lock)
        if self.lock_path == self.output_root or self.lock_path.is_relative_to(self.output_root):
            raise AdapterError('owner lock must be outside new output root')
        self.supervisor_identity = file_identity(sys.executable)
        if len(canonical(self.base_record())) > self.limits.max_receipt_bytes // 2:
            raise AdapterError('metadata exceeds reserved receipt budget')
        if self.output_root.exists() or self.output_root.is_symlink():
            raise FileExistsError('existing attempt/partial output is never overwritten')
        if not SERIAL.acquire(blocking=False): raise AdapterError('another adapter attempt is active')
        self.serial_held = True
        try:
            self.lock_data = canonical({'attempt_id': uuid.uuid4().hex, 'pid': os.getpid(),
                                        'run_id': self.binding.run_id, 'output_root': str(self.output_root)})
            with self.lock_path.open('xb') as lock:
                lock.write(self.lock_data); lock.flush(); os.fsync(lock.fileno()); self.lock_stat = os.fstat(lock.fileno())
            self.lock_held = True
            self.output_root.mkdir(mode=0o700); self.root_created = True
            self.queue = ByteQueue(self.limits.queue_bytes, self.limits.queue_rows)
            self.attempt = self.base_record()
            self.attempt['state'] = 'prepared'
            self.attempt_ref = durable(self.output_root/'attempt.json', self.attempt, self.limits.max_receipt_bytes)
            for name, maximum in (('stdout', self.limits.max_stdout_bytes), ('stderr', self.limits.max_stderr_bytes),
                                  ('samples', self.limits.max_samples_bytes)):
                self.streams[name] = StreamRecord(self.output_root/(name + ('.jsonl' if name == 'samples' else '.bin')), maximum)
            self.resources = self.resources or Resources()
            available = self.resources.available(); free = self.resources.disk(self.output_root)
            if type(available) is not int or available < self.limits.initial_available_bytes:
                raise AdapterError('initial_available_memory_guard')
            if type(free) is not int or free < self.limits.disk_floor_bytes + self.limits.retained_budget:
                raise AdapterError('initial_disk_retention_guard')
            self.executable_before = file_identity(self.argv[0])
            if time.monotonic()-self.t0 >= self.limits.deadline_seconds:
                raise AdapterError('own_child_timeout')
            self.process = self.launcher(self.argv, self.cwd, dict(self.binding.environment)); self.started = True
            start = {**self.base_record(), 'state':'started', 'pid':self.process.pid,
                     'backend':self.process.kind, 'executable_before':self.executable_before,
                     'initial_available_bytes':available, 'initial_free_bytes':free, 'attempt':self.attempt_ref}
            self.started_ref = durable(self.output_root/'started.json', start, self.limits.max_receipt_bytes)
            for name in ('stdout', 'stderr'):
                thread = threading.Thread(target=self.read_pipe, args=(name,), name='owned-'+name, daemon=True)
                self.readers.append(thread); thread.start()
            self.monitor = threading.Thread(target=self.supervise, name='owned-monitor', daemon=True)
            self.monitor.start()
            return self
        except BaseException as exc:
            partial_owner = getattr(exc, 'owned_process', None)
            if partial_owner is not None:
                # A failed constructor can already own a launched process. Its
                # verified or incomplete cleanup state crosses the API boundary.
                self.process = partial_owner
                self.started = partial_owner.pid is not None
                self.exit_code = partial_owner.last_exit_code
                self.cleanup_complete = partial_owner.constructor_cleanup_complete
            self.fail(str(exc) if isinstance(exc, AdapterError) else 'launch_failure', exc)
            try:
                if self.process and partial_owner is None: self.finish_process()
                if self.root_created: self.finalize()
            finally:
                self.release()
            raise

    def base_record(self):
        return {'schema':'rust-duty-owned-process/v1', 'command':self.argv, 'cwd':self.cwd,
                'host_binding': self.binding.record(), 'limits':asdict(self.limits),
                'supervisor_python':self.supervisor_identity,
                'started_unix': self.started_unix,
                'clock':'time.monotonic; elapsed not derived from wall clock',
                'memory_scope':'sampled own direct child RSS / Windows working set; not instantaneous peak or commit guarantee',
                'proof_scope':'transport only; no numerical/candidate/Windows-production admission'}

    def read_pipe(self, name):
        pipe, record = getattr(self.process, name), self.streams[name]
        pending = bytearray()
        try:
            while not self.cancel.is_set():
                block = pipe.read(65536, self.cancel)
                if not block:
                    record.eof = not self.cancel.is_set()
                    break
                try: record.add(block)
                except AdapterError:
                    self.fail(name + '_bytes_limit'); break
                if name != 'stdout' or self.limits.stdout_mode != 'jsonl': continue
                # Split incrementally; never concatenate an unbounded read to a row.
                cursor = 0
                while cursor < len(block):
                    end = block.find(b'\n', cursor)
                    end = len(block) if end < 0 else end + 1
                    piece = block[cursor:end]; cursor = end
                    if len(pending) + len(piece) > self.limits.max_row_bytes:
                        self.fail('stdout_row_limit'); return
                    pending.extend(piece)
                    if pending.endswith(b'\n'):
                        if not self.queue.put(bytes(pending), self.stop, self.limits.queue_wait_seconds):
                            if not self.stop.is_set(): self.fail('stdout_queue_backpressure')
                            return
                        pending.clear()
            if pending and not self.stop.is_set(): self.fail('stdout_partial_row')
        except BaseException as exc:
            self.fail(name + '_reader_failure', exc)
        finally:
            try: record.close()
            except BaseException as exc: self.fail(name + '_durability_failure', exc)

    def observe(self):
        elapsed = time.monotonic() - self.t0
        rss = self.process.rss() if self.process.poll() is None else None
        available, free = self.resources.available(), self.resources.disk(self.output_root)
        if (rss is not None and (type(rss) is not int or rss < 0)) or type(available) is not int or available < 0 or type(free) is not int or free < 0:
            raise AdapterError('invalid resource observation')
        if rss is not None: self.peak_rss = max(self.peak_rss, rss)
        self.sample_count += 1
        if self.sample_count > self.limits.max_samples: raise AdapterError('sample count exceeded')
        self.streams['samples'].add(canonical({'elapsed_seconds':elapsed, 'rss_bytes':rss,
            'mem_available_bytes':available, 'free_bytes':free}))
        self.streams['samples'].stream.flush(); os.fsync(self.streams['samples'].stream.fileno())
        if rss is not None and rss > self.limits.rss_bytes: self.fail('own_child_rss_ceiling')
        elif elapsed >= self.limits.deadline_seconds: self.fail('own_child_timeout')
        elif free < self.limits.disk_floor_bytes: self.fail('own_child_disk_reserve_guard')

    def supervise(self):
        try:
            next_sample = time.monotonic()
            while True:
                now = time.monotonic()
                if now >= next_sample:
                    self.observe(); next_sample = now + self.limits.sample_seconds
                self.exit_code = self.process.poll()
                if self.exit_code is not None or self.stop.is_set(): break
                self.stop.wait(min(.02, max(0, next_sample-time.monotonic())))
        except BaseException as exc:
            self.fail('resource_observation_failure', exc)
        finally:
            self.finish_process()
            if self.exit_code is not None and self.exit_code != 0: self.fail('child_exit_failure')
            try:
                self.executable_after = file_identity(self.argv[0])
                if self.executable_after != self.executable_before: self.fail('executable_changed')
            except BaseException as exc: self.fail('executable_recheck_failure', exc)
            self.process_finished_elapsed = time.monotonic()-self.t0
            self.streams['samples'].eof = True
            try:
                self.streams['samples'].close()
                transport = self.result_record('transport_stopped')
                self.transport_ref = durable(self.output_root/'transport.json', transport, self.limits.max_receipt_bytes)
            except BaseException as exc: self.fail('transport_receipt_failure', exc)
            self.done.set()

    def finish_process(self):
        try:
            # Kill still-owned descendants even after normal root exit. Linux root
            # has not been reaped; Windows job membership is a kernel object.
            self.process.stop_tree()
            end = time.monotonic() + self.limits.drain_seconds
            while self.process.poll() is None and time.monotonic() < end: time.sleep(.01)
            self.exit_code = self.process.reap()
            if self.exit_code is None: raise AdapterError('owned child did not terminate')
            for thread in self.readers:
                thread.join(max(0, end-time.monotonic()))
            if any(thread.is_alive() for thread in self.readers):
                self.fail('incomplete_stream_drain')
            self.cancel.set()
            for thread in self.readers: thread.join(.25)
            if any(thread.is_alive() for thread in self.readers):
                self.cleanup_complete = False; self.fail('reader_cleanup_incomplete'); return
            if not self.streams_complete(('stdout','stderr')):
                self.fail('incomplete_stream_retention')
            self.process.close()
        except BaseException as exc:
            self.cleanup_complete = False; self.fail('owned_cleanup_failure', exc)
            # Win32 kill-on-close remains available even if TerminateJobObject
            # fails. Keep the serialization lock: no success/retry is implied.
            try:
                if hasattr(self.process, 'emergency_stop'): self.process.emergency_stop()
            except BaseException:
                pass
            self.cancel.set()
            for thread in self.readers: thread.join(.25)

    def streams_complete(self, names=None):
        names = tuple(self.streams) if names is None else names
        if not names: return False
        return all(name in self.streams and self.streams[name].eof
            and not self.streams[name].truncated
            and self.streams[name].bytes == self.streams[name].observed
            and self.streams[name].hash.digest() == self.streams[name].observed_hash.digest()
            for name in names)

    def ensure_transport_complete(self):
        if not self.streams_complete(('stdout','stderr')):
            self.fail('incomplete_stream_retention')
        if not self.cleanup_complete: self.fail('owned_cleanup_failure')
        if self.reason or self.exit_code != 0:
            raise AdapterError(self.reason or 'child_exit_failure')

    def jsonl(self):
        if not self.started or self.limits.stdout_mode != 'jsonl' or self.iterator_used:
            raise AdapterError('single JSONL iterator requires a started JSONL attempt')
        self.iterator_used = True
        try:
            while True:
                line = self.queue.get(self.done, self.stop)
                if line is None: break
                if self.stop.is_set(): break
                try:
                    value = json.loads(line.decode('utf-8'), parse_constant=reject_constant,
                                       object_pairs_hook=unique_object)
                    validate_json(value)
                    if not isinstance(value, dict): raise ValueError('JSONL row must be an object')
                except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
                    self.fail('malformed_jsonl', exc); raise AdapterError('invalid JSONL row') from exc
                self.rows += 1
                if self.rows > self.limits.max_rows:
                    self.fail('stdout_row_count_limit'); raise AdapterError('row count exceeded')
                yield value
            self.done.wait()
            self.ensure_transport_complete()
            self.iterator_complete = True
        except GeneratorExit:
            self.fail('consumer_incomplete'); raise
        except BaseException as exc:
            if self.reason is None: self.fail('consumer_failure', exc)
            raise

    def wait(self):
        if self.limits.stdout_mode != 'bytes':
            raise AdapterError('JSONL stages must exhaust jsonl()')
        self.done.wait()
        self.ensure_transport_complete()
        self.iterator_complete = True
        return self.exit_code

    def result_record(self, state):
        completed = (state == 'completed' and self.reason is None and self.exit_code == 0
                     and self.iterator_complete and self.cleanup_complete and self.streams_complete())
        return {**self.base_record(), 'state':state, 'completed':completed,
            'started':self.started, 'pid':getattr(self.process,'pid',None), 'exit_code':self.exit_code,
            'signal':-self.exit_code if platform.system()=='Linux' and self.exit_code is not None and self.exit_code<0 else None,
            'timed_out':self.reason == 'own_child_timeout', 'resource_stop_reason':self.reason,
            'error_type':self.error, 'finished_unix':time.time(), 'duration_seconds':time.monotonic()-self.t0,
            'process_duration_seconds':getattr(self, 'process_finished_elapsed', None),
            'peak_sampled_rss_bytes':self.peak_rss, 'rss_ceiling_bytes':self.limits.rss_bytes,
            'sample_count':self.sample_count, 'rows':self.rows, 'consumer_complete':self.iterator_complete,
            'cleanup_complete':self.cleanup_complete,
            'constructor_cleanup_complete':getattr(self.process,'constructor_cleanup_complete',None),
            'windows_job_empty_verified':getattr(self.process,'tree_empty_verified',None),
            'parent_already_in_windows_job':getattr(self.process,'parent_in_job',None),
            'executable_before':self.executable_before,
            'executable_after':self.executable_after, 'streams':{k:v.record() for k,v in self.streams.items()},
            'queue_peak_bytes':self.queue.peak_bytes if self.queue else 0,
            'queue_peak_rows':self.queue.peak_rows if self.queue else 0,
            'attempt':getattr(self, 'attempt_ref', None), 'started_record':getattr(self, 'started_ref', None),
            'transport_record':getattr(self, 'transport_ref', None)}

    def finalize(self):
        if any(thread.is_alive() for thread in self.readers):
            raise AdapterError('cannot seal evidence while a reader remains live')
        for record in self.streams.values(): record.close()
        complete = (self.reason is None and self.exit_code == 0 and self.iterator_complete
                    and self.cleanup_complete and self.streams_complete())
        partial = self.started and (not self.iterator_complete or any(v.truncated or not v.eof for k,v in self.streams.items() if k!='samples'))
        state = 'completed' if complete else ('partial' if partial else 'failed')
        self.receipt = self.result_record(state)
        reference = durable(self.output_root/'terminal.json', self.receipt, self.limits.max_receipt_bytes)
        durable(self.output_root/'terminal.sha256.json', reference, self.limits.max_receipt_bytes)

    def check_lock(self):
        info = self.lock_path.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400
            or (info.st_dev,info.st_ino)!=(self.lock_stat.st_dev,self.lock_stat.st_ino)
            or self.lock_contents()!=self.lock_data):
            raise AdapterError('owner lock changed; foreign replacement preserved')

    def lock_contents(self):
        with self.lock_path.open('rb') as stream:
            return stream.read(len(self.lock_data)+1)

    def release(self):
        if not self.cleanup_complete and self not in INCOMPLETE_ATTEMPTS:
            INCOMPLETE_ATTEMPTS.append(self)  # Retain owned state/storage until inspection.
        try:
            if self.lock_held:
                self.check_lock()
                if self.cleanup_complete:
                    self.lock_path.unlink(); self.lock_held = False
                # Incomplete cleanup intentionally retains the lock and blocks reuse.
        finally:
            if self.serial_held and self.cleanup_complete:
                SERIAL.release(); self.serial_held = False

    def __exit__(self, kind, exc, trace):
        try:
            if exc is not None: self.fail('consumer_failure', exc)
            elif not self.iterator_complete: self.fail('consumer_incomplete')
            self.done.wait(self.limits.drain_seconds + 7)
            if not self.done.is_set():
                self.cleanup_complete = False; self.fail('supervisor_cleanup_incomplete')
                raise AdapterError('supervisor did not finalize; attempt remains incomplete')
            try: self.check_lock()
            except (OSError, AdapterError) as lock_error: self.fail('owner_lock_changed', lock_error)
            self.finalize()
        finally:
            self.release()
        if exc is None and not self.receipt['completed']:
            raise AdapterError(self.reason or 'child_exit_failure')
        return False


def reject_constant(value): raise ValueError('nonfinite JSON constant')

def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError('duplicate JSON object key')
        value[key] = item
    return value

def validate_json(value):
    # Iterative finite/depth checks; Python's parser nesting errors fail closed too.
    todo = [(value, 0)]
    while todo:
        current, depth = todo.pop()
        if depth > 64: raise ValueError('JSON nesting exceeds 64')
        if isinstance(current, float) and not math.isfinite(current): raise ValueError('nonfinite JSON number')
        if isinstance(current, dict): todo.extend((v, depth+1) for v in current.values())
        elif isinstance(current, list): todo.extend((v, depth+1) for v in current)


def verify_attempt(output_root, *, require_completed=False, maximum_receipt_bytes=MIB):
    """Read-only integrity check; caller must separately trust/pin the root receipt.

    Self-hashes are not signatures. All references are fixed local filenames;
    untrusted receipt paths cannot escape the attempt directory.
    """
    root = safe_parent(Path(output_root).absolute())
    if not root.is_dir(): raise AdapterError('missing attempt directory')
    def read_small(name):
        path = safe_parent(root/name)
        if path.stat().st_size > maximum_receipt_bytes: raise AdapterError('receipt exceeds read bound')
        data = path.read_bytes()
        try:
            value = json.loads(data.decode('utf-8'), parse_constant=reject_constant, object_pairs_hook=unique_object)
            validate_json(value)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise AdapterError('invalid receipt JSON') from exc
        return value, data
    def check_bytes(reference, name, maximum):
        if not isinstance(reference,dict) or reference.get('path') != name:
            raise AdapterError('receipt path mismatch')
        size = reference.get('bytes'); expected = reference.get('sha256')
        if type(size) is not int or not 0 <= size <= maximum or not isinstance(expected,str) or not HEX.fullmatch(expected):
            raise AdapterError('invalid stream identity')
        path = safe_parent(root/name)
        if path.stat().st_size != size: raise AdapterError('retained size differs: '+name)
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            while True:
                block = stream.read(65536)
                if not block: break
                sha.update(block)
        if sha.hexdigest()!=expected: raise AdapterError('retained hash differs: '+name)
    seal,_ = read_small('terminal.sha256.json')
    check_bytes(seal,'terminal.json',maximum_receipt_bytes)
    receipt,_ = read_small('terminal.json')
    if receipt.get('schema')!='rust-duty-owned-process/v1': raise AdapterError('unknown receipt schema')
    limits = Limits(**receipt['limits']).validate()
    for key,name in (('attempt','attempt.json'),('started_record','started.json'),('transport_record','transport.json')):
        if receipt.get(key) is not None:
            check_bytes(receipt[key],name,limits.max_receipt_bytes)
    expected_streams={'stdout':('stdout.bin',limits.max_stdout_bytes),
                      'stderr':('stderr.bin',limits.max_stderr_bytes),
                      'samples':('samples.jsonl',limits.max_samples_bytes)}
    if set(receipt.get('streams',{})) != set(expected_streams): raise AdapterError('stream coverage differs')
    for key,(name,maximum) in expected_streams.items(): check_bytes(receipt['streams'][key],name,maximum)
    if require_completed and receipt.get('completed') is not True: raise AdapterError('attempt is not complete')
    if receipt.get('completed') is True:
        if (receipt.get('state')!='completed' or type(receipt.get('exit_code')) is not int or receipt['exit_code']!=0
            or receipt.get('resource_stop_reason') is not None or receipt.get('timed_out') is not False
            or receipt.get('cleanup_complete') is not True or receipt.get('consumer_complete') is not True
            or receipt.get('executable_before')!=receipt.get('executable_after')):
            raise AdapterError('inconsistent completion claim')
        for record in receipt['streams'].values():
            if (record.get('eof_observed') is not True or record.get('truncated') is not False
                or record.get('observed_bytes')!=record['bytes'] or record.get('observed_sha256')!=record['sha256']):
                raise AdapterError('incomplete retained stream')
        if receipt['host_binding']['observed_host']['system']=='Windows' and receipt.get('windows_job_empty_verified') is not True:
            raise AdapterError('Windows job cleanup not verified')
    return receipt
