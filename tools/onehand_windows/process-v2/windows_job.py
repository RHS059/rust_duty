"""Original ctypes Windows 10+/64-bit process backend. No native runs at import.

Atomic JOB_LIST assignment closes the suspended/unassigned process race. Only
our unnamed, non-inheritable job is terminated. Pipes use overlapped reads;
there are no selectors, POSIX process APIs, or Popen private attributes here.
"""
from __future__ import annotations
import ctypes as C
import os
import subprocess
import sys
import threading
import time
import uuid

U32, I32, U64, SIZE, HANDLE = C.c_uint32, C.c_int32, C.c_uint64, C.c_size_t, C.c_void_p
BOOL = I32
PTR = C.c_void_p

class Security(C.Structure):
    _fields_ = [('length', U32), ('descriptor', PTR), ('inherit', BOOL)]
class Startup(C.Structure):
    _fields_ = [('cb', U32), ('reserved', C.c_wchar_p), ('desktop', C.c_wchar_p),
                ('title', C.c_wchar_p), ('x', U32), ('y', U32), ('xsize', U32),
                ('ysize', U32), ('xchars', U32), ('ychars', U32), ('fill', U32),
                ('flags', U32), ('show', C.c_uint16), ('cbreserved', C.c_uint16),
                ('reserved2', PTR), ('stdin', HANDLE), ('stdout', HANDLE), ('stderr', HANDLE)]
class StartupEx(C.Structure):
    _fields_ = [('startup', Startup), ('attributes', PTR)]
class ProcessInfo(C.Structure):
    _fields_ = [('process', HANDLE), ('thread', HANDLE), ('pid', U32), ('tid', U32)]
class BasicLimits(C.Structure):
    _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64), ('flags', U32),
                ('min_working_set', SIZE), ('max_working_set', SIZE), ('active_processes', U32),
                ('affinity', SIZE), ('priority', U32), ('scheduling', U32)]
class ExtendedLimits(C.Structure):
    _fields_ = [('basic', BasicLimits), ('io_counters', U64 * 6), ('process_memory', SIZE),
                ('job_memory', SIZE), ('peak_process', SIZE), ('peak_job', SIZE)]
class JobAccounting(C.Structure):
    _fields_ = [('user_time', C.c_int64), ('kernel_time', C.c_int64),
                ('period_user_time', C.c_int64), ('period_kernel_time', C.c_int64),
                ('page_faults', U32), ('total_processes', U32), ('active_processes', U32),
                ('terminated_processes', U32)]
class MemoryStatus(C.Structure):
    _fields_ = [('length', U32), ('load', U32), ('total_phys', U64), ('available_phys', U64),
                ('total_page', U64), ('available_page', U64), ('total_virtual', U64),
                ('available_virtual', U64), ('available_extended', U64)]
class ProcessMemory(C.Structure):
    _fields_ = [('cb', U32), ('page_faults', U32), ('peak_working_set', SIZE),
                ('working_set', SIZE), ('peak_paged_pool', SIZE), ('paged_pool', SIZE),
                ('peak_nonpaged_pool', SIZE), ('nonpaged_pool', SIZE),
                ('pagefile', SIZE), ('peak_pagefile', SIZE)]
class Overlapped(C.Structure):
    _fields_ = [('internal', SIZE), ('internal_high', SIZE), ('offset', U32),
                ('offset_high', U32), ('event', HANDLE)]

JOB_LIST, HANDLE_LIST = 0x2000D, 0x20002
KILL_ON_CLOSE = 0x2000
ERROR_IO_PENDING, ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED = 997, 109, 995
ERROR_IO_INCOMPLETE = 996
# Quarantine is deliberate: pending kernel storage/uncertain handles stay owned.
INCOMPLETE_OWNERS = []
PENDING_PIPES = []

class WindowsLaunchError(OSError):
    def __init__(self, owner, cause):
        super().__init__("owned Windows launch failed: " + type(cause).__name__)
        self.owned_process = owner

class PendingReadError(OSError): pass

class HandleSetupError(OSError):
    def __init__(self, handle, cause):
        super().__init__("owned setup handle close failed")
        self.owned_handles = [handle]

INFINITE, WAIT_TIMEOUT, WAIT_OBJECT_0 = 0xFFFFFFFF, 258, 0
INVALID_HANDLE = C.c_void_p(-1).value

class WinAPI:
    """Small injectable boundary; tests can audit call order without loading DLLs."""
    def __init__(self):
        if os.name != 'nt' or sys.maxsize <= 2**32 or sys.getwindowsversion().major < 10:
            raise RuntimeError('Windows 10+/Server 2016+ and 64-bit Python required')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.p = C.WinDLL('psapi', use_last_error=True)
        signatures = {
            'CreateJobObjectW': (HANDLE, [PTR, C.c_wchar_p]),
            'SetInformationJobObject': (BOOL, [HANDLE, I32, PTR, U32]),
            'TerminateJobObject': (BOOL, [HANDLE, U32]),
            'TerminateProcess': (BOOL, [HANDLE, U32]),
            'QueryInformationJobObject': (BOOL, [HANDLE, I32, PTR, U32, PTR]),
            'CloseHandle': (BOOL, [HANDLE]),
            'InitializeProcThreadAttributeList': (BOOL, [PTR, U32, U32, C.POINTER(SIZE)]),
            'UpdateProcThreadAttribute': (BOOL, [PTR, U32, SIZE, PTR, SIZE, PTR, PTR]),
            'DeleteProcThreadAttributeList': (None, [PTR]),
            'CreateProcessW': (BOOL, [C.c_wchar_p, C.c_wchar_p, PTR, PTR, BOOL, U32,
                                     PTR, C.c_wchar_p, PTR, C.POINTER(ProcessInfo)]),
            'IsProcessInJob': (BOOL, [HANDLE, HANDLE, C.POINTER(BOOL)]),
            'GetCurrentProcess': (HANDLE, []),
            'WaitForSingleObject': (U32, [HANDLE, U32]),
            'GetExitCodeProcess': (BOOL, [HANDLE, C.POINTER(U32)]),
            'GlobalMemoryStatusEx': (BOOL, [C.POINTER(MemoryStatus)]),
            'CreateNamedPipeW': (HANDLE, [C.c_wchar_p, U32, U32, U32, U32, U32, U32, PTR]),
            'CreateFileW': (HANDLE, [C.c_wchar_p, U32, U32, PTR, U32, U32, HANDLE]),
            'CreateEventW': (HANDLE, [PTR, BOOL, BOOL, C.c_wchar_p]),
            'ReadFile': (BOOL, [HANDLE, PTR, U32, C.POINTER(U32), C.POINTER(Overlapped)]),
            'GetOverlappedResult': (BOOL, [HANDLE, C.POINTER(Overlapped), C.POINTER(U32), BOOL]),
            'CancelIoEx': (BOOL, [HANDLE, C.POINTER(Overlapped)]),
            'ResetEvent': (BOOL, [HANDLE]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.k, name)
            function.restype, function.argtypes = result, args
        self.p.GetProcessMemoryInfo.restype = BOOL
        self.p.GetProcessMemoryInfo.argtypes = [HANDLE, C.POINTER(ProcessMemory), U32]

    @staticmethod
    def check(value, name):
        if not value:
            raise OSError(C.get_last_error(), name)
        return value

    def available(self):
        value = MemoryStatus(); value.length = C.sizeof(value)
        self.check(self.k.GlobalMemoryStatusEx(C.byref(value)), 'GlobalMemoryStatusEx')
        return int(value.available_phys)

    def create_job(self):
        job = self.check(self.k.CreateJobObjectW(None, None), 'CreateJobObjectW')
        value = ExtendedLimits(); value.basic.flags = KILL_ON_CLOSE
        try:
            self.check(self.k.SetInformationJobObject(job, 9, C.byref(value), C.sizeof(value)),
                       'SetInformationJobObject(KILL_ON_JOB_CLOSE)')
        except BaseException:
            try: self.close(job)
            except BaseException as close_error: raise HandleSetupError(job, close_error)
            raise
        return job

    def inherited_job(self):
        present = BOOL()
        self.check(self.k.IsProcessInJob(self.k.GetCurrentProcess(), None, C.byref(present)),
                   'IsProcessInJob(parent)')
        # Nested containment is accepted only if atomic CreateProcess succeeds.
        return bool(present.value)

    def pipe(self):
        name = r'\\.\pipe\rust-duty-owned-' + uuid.uuid4().hex
        reader = self.k.CreateNamedPipeW(name, 0x1 | 0x40000000 | 0x80000,
                                         0x8, 1, 65536, 65536, 0, None)
        if reader == INVALID_HANDLE:
            raise OSError(C.get_last_error(), 'CreateNamedPipeW')
        security = Security(C.sizeof(Security), None, True)
        writer = self.k.CreateFileW(name, 0x40000000, 0, C.byref(security), 3, 0x80, None)
        if writer == INVALID_HANDLE:
            error = C.get_last_error()
            try: self.close(reader)
            except BaseException as close_error: raise HandleSetupError(reader, close_error)
            raise OSError(error, 'CreateFileW(pipe writer)')
        return reader, writer

    def nul(self):
        security = Security(C.sizeof(Security), None, True)
        handle = self.k.CreateFileW('NUL', 0x80000000, 3, C.byref(security), 3, 0x80, None)
        if handle == INVALID_HANDLE:
            raise OSError(C.get_last_error(), 'CreateFileW(NUL)')
        return handle

    def create_in_job(self, job, argv, cwd, env, stdin, stdout, stderr, *, adopt=None):
        size = SIZE()
        self.k.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
        if not size.value or size.value > 65536:
            raise RuntimeError('invalid attribute-list size')
        storage = C.create_string_buffer(size.value)
        self.check(self.k.InitializeProcThreadAttributeList(storage, 2, 0, C.byref(size)),
                   'InitializeProcThreadAttributeList')
        try:
            jobs, handles = (HANDLE * 1)(job), (HANDLE * 3)(stdin, stdout, stderr)
            for key, value in ((JOB_LIST, jobs), (HANDLE_LIST, handles)):
                self.check(self.k.UpdateProcThreadAttribute(storage, 0, key, value,
                                                           C.sizeof(value), None, None),
                           'UpdateProcThreadAttribute')
            startup = StartupEx(); startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = stdin, stdout, stderr
            startup.attributes = C.cast(storage, PTR)
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            # Empty environment still has the required double terminator.
            environment = C.create_unicode_buffer('\0'.join(k + '=' + env[k] for k in sorted(env, key=str.upper)) + '\0\0')
            info = ProcessInfo()
            self.check(self.k.CreateProcessW(argv[0], command, None, None, True,
                0x80000 | 0x400 | 0x08000000, environment, cwd, C.byref(startup), C.byref(info)),
                'CreateProcessW(atomic JOB_LIST; no fallback/breakaway)')
            # Transfer ownership before attribute-list cleanup can raise.
            if adopt is not None: adopt(info)
            # CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT.
            return info
        finally:
            self.k.DeleteProcThreadAttributeList(storage)

    def in_job(self, process, job):
        present = BOOL()
        self.check(self.k.IsProcessInJob(process, job, C.byref(present)), 'IsProcessInJob(child)')
        return bool(present.value)

    def rss(self, process):
        value = ProcessMemory(); value.cb = C.sizeof(value)
        self.check(self.p.GetProcessMemoryInfo(process, C.byref(value), C.sizeof(value)), 'GetProcessMemoryInfo')
        return int(value.working_set)

    def poll(self, process):
        wait = self.k.WaitForSingleObject(process, 0)
        if wait == WAIT_TIMEOUT:
            return None
        if wait != WAIT_OBJECT_0:
            raise OSError(C.get_last_error(), 'WaitForSingleObject')
        code = U32()
        self.check(self.k.GetExitCodeProcess(process, C.byref(code)), 'GetExitCodeProcess')
        return int(code.value)  # Preserve unsigned Windows exit values, including 259.

    def close(self, handle):
        if handle:
            self.check(self.k.CloseHandle(handle), 'CloseHandle')

    def active_processes(self, job):
        value = JobAccounting()
        self.check(self.k.QueryInformationJobObject(job, 1, C.byref(value), C.sizeof(value), None),
                   'QueryInformationJobObject(owned job)')
        return int(value.active_processes)

    def terminate_process(self, process):
        self.check(self.k.TerminateProcess(process, 0xE0000001), 'TerminateProcess(own new child)')

    def terminate(self, job):
        self.check(self.k.TerminateJobObject(job, 0xE0000001), 'TerminateJobObject(owned job)')


class WindowsPipe:
    cancellation_grace_seconds = 1.0

    def __init__(self, api, handle):
        self.api, self.handle = api, handle
        self.event = api.check(api.k.CreateEventW(None, True, False, None), 'CreateEventW')
        self.pending = None
        self.cancellation_attempted = False
        self.quarantined = False
        self.close_failed = set()

    def read(self, count, cancel):
        while not cancel.is_set():
            value = self._read_once(count, cancel)
            if value is not None: return value
        return b''

    def _cancel_and_observe(self):
        """Never release pending buffer/OVERLAPPED merely because cancel returned."""
        if self.pending is None: return True
        if self.quarantined: return False
        buffer, operation = self.pending
        if not self.cancellation_attempted:
            self.cancellation_attempted = True
            try: self.api.k.CancelIoEx(self.handle, C.byref(operation))
            except BaseException: pass  # Completion still must be observed.
        end = time.monotonic() + self.cancellation_grace_seconds
        while True:
            got = U32()
            try:
                complete = self.api.k.GetOverlappedResult(self.handle, C.byref(operation), C.byref(got), False)
                error = 0 if complete else C.get_last_error()
            except BaseException:
                break
            if complete or error in (ERROR_OPERATION_ABORTED, ERROR_BROKEN_PIPE):
                self.pending = None
                return True
            if error != ERROR_IO_INCOMPLETE or time.monotonic() >= end: break
            time.sleep(.01)
        if not self.quarantined:
            self.quarantined = True
            PENDING_PIPES.append(self)  # Strong ownership survives exception/GC.
        return False

    def _read_once(self, count, cancel):
        if self.pending is not None: raise PendingReadError('previous read still pending')
        api = self.api
        buffer = C.create_string_buffer(count)
        got = U32(); operation = Overlapped(); operation.event = self.event
        api.check(api.k.ResetEvent(self.event), 'ResetEvent')
        self.pending = (buffer, operation)
        self.cancellation_attempted = False
        submitted = True  # Conservatively own the operation across call exceptions.
        try:
            ready = api.k.ReadFile(self.handle, buffer, count, None, C.byref(operation))
            if not ready:
                error = C.get_last_error()
                if error == ERROR_BROKEN_PIPE:
                    self.pending = None
                    return b''
                if error != ERROR_IO_PENDING:
                    self.pending = None
                    raise OSError(error, 'ReadFile')
                submitted = True
                while True:
                    wait = api.k.WaitForSingleObject(self.event, 20)
                    if wait == WAIT_OBJECT_0: break
                    if wait != WAIT_TIMEOUT: raise OSError(C.get_last_error(), 'pipe wait')
                    if cancel.is_set():
                        if not self._cancel_and_observe():
                            raise PendingReadError('pipe cancellation completion unverified')
                        return b''
            else:
                submitted = True
            if not api.k.GetOverlappedResult(self.handle, C.byref(operation), C.byref(got), False):
                error = C.get_last_error()
                if error in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED):
                    self.pending = None
                    return b''
                raise OSError(error, 'GetOverlappedResult')
            self.pending = None
            return buffer.raw[:got.value] if got.value else None
        except BaseException as exc:
            if submitted and self.pending is not None:
                if not self._cancel_and_observe():
                    raise PendingReadError('pending read storage and handles retained') from exc
            elif not submitted:
                self.pending = None
            raise

    def close(self):
        if self.pending is not None:
            # An unverified operation owns both handles and its storage. Closing
            # either handle or freeing storage here would hide the lifecycle bug.
            raise PendingReadError('cannot close handles while read completion is unverified')
        errors = []
        for name in ('handle', 'event'):
            handle = getattr(self, name)
            if not handle: continue
            if name in self.close_failed:
                errors.append(OSError('previous close outcome unverified')); continue
            try: self.api.close(handle); setattr(self, name, None)
            except BaseException as exc:
                self.close_failed.add(name); errors.append(exc)
        if errors:
            if not self.quarantined: self.quarantined = True; PENDING_PIPES.append(self)
            raise errors[0]


class WindowsProcess:
    """Every acquired handle belongs to the object, including failed launches."""
    kind = 'windows-job-list-overlapped-v2'
    def __init__(self, argv, cwd, env, api=None, pipe_factory=WindowsPipe):
        self.api = api or WinAPI()
        self.pid = None; self.process = None; self.job = None
        self.stdout = self.stderr = None
        self.parent_in_job = False; self.tree_empty_verified = False
        self.last_exit_code = None; self.constructor_cleanup_complete = None
        self.handles = {}; self.close_failed = set(); self.cleanup_errors = []
        try:
            self.parent_in_job = self.api.inherited_job()
            self.job = self.api.create_job(); self.handles['job'] = self.job
            for name in ('stdout', 'stderr'):
                reader, writer = self.api.pipe()
                self.handles[name+'_reader'] = reader; self.handles[name+'_writer'] = writer
            stdin = self.api.nul(); self.handles['stdin'] = stdin
            info = self.api.create_in_job(self.job, argv, cwd, env, stdin,
                self.handles['stdout_writer'], self.handles['stderr_writer'], adopt=self._adopt_created)
            self._adopt_created(info)
            error = self._close_slot('thread')
            if error: raise error
            if not self.api.in_job(self.process, self.job):
                self.api.terminate_process(self.process)
                raise RuntimeError('atomic job association not observed')
            for name in ('stdout', 'stderr'):
                pipe = pipe_factory(self.api, self.handles[name+'_reader'])
                setattr(self, name, pipe); self.handles[name+'_reader'] = None
            # All independent parent standard handles are attempted. An error is
            # inside this ownership try, not an escaping constructor finally.
            errors = [self._close_slot(name) for name in ('stdout_writer','stderr_writer','stdin')]
            if any(errors): raise next(error for error in errors if error)
        except BaseException as exc:
            for index, handle in enumerate(getattr(exc, 'owned_handles', [])):
                name = 'uncertain_setup_'+str(index)
                self.handles[name] = handle; self.close_failed.add(name)
            self._cleanup_failed_launch()
            if not self.constructor_cleanup_complete: INCOMPLETE_OWNERS.append(self)
            raise WindowsLaunchError(self, exc) from exc

    def _adopt_created(self, info):
        self.process, self.pid = info.process, int(info.pid)
        self.handles['process'] = self.process; self.handles['thread'] = info.thread

    def _close_slot(self, name):
        handle = self.handles.get(name)
        if not handle: return None
        if name in self.close_failed: return OSError('previous owned handle close failed: '+name)
        try:
            self.api.close(handle); self.handles[name] = None
            if name in ('job','process'): setattr(self,name,None)
            return None
        except BaseException as exc:
            self.close_failed.add(name)
            return exc

    def _cleanup_failed_launch(self):
        if self.process is not None:
            try: self.stop_tree()
            except BaseException as exc: self.cleanup_errors.append(type(exc).__name__)
            try: self.last_exit_code = self.reap()
            except BaseException as exc: self.cleanup_errors.append(type(exc).__name__)
        try: self.close()
        except BaseException as exc: self.cleanup_errors.append(type(exc).__name__)
        self.constructor_cleanup_complete = (not self.cleanup_errors and not self.close_failed
            and not any(self.handles.values()) and self.stdout is None and self.stderr is None
            and (self.pid is None or self.tree_empty_verified))

    def poll(self): return self.api.poll(self.process)
    def rss(self): return self.api.rss(self.process)
    def stop_tree(self):
        if self.job: self.api.terminate(self.job)
    def emergency_stop(self):
        error = self._close_slot('job')
        if error: raise error
    def reap(self):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            code = self.poll()
            if code is not None and self.api.active_processes(self.job) == 0:
                self.tree_empty_verified = True; self.last_exit_code = code
                return code
            time.sleep(.01)
        raise RuntimeError('owned job did not become empty within cleanup bound')
    def close(self):
        errors = []
        # Job first gives kill-on-close fallback even when termination failed.
        for name in ('job','process',*tuple(k for k in self.handles if k not in ('job','process'))):
            error = self._close_slot(name)
            if error: errors.append(error)
        for name in ('stdout','stderr'):
            pipe = getattr(self,name)
            if pipe:
                try: pipe.close(); setattr(self,name,None)
                except BaseException as exc: errors.append(exc)
        if errors: raise errors[0]
