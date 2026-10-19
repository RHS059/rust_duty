"""Exact reviewer failures plus adjacent ownership edges. Mocks only.

These tests deliberately retain a production lock on unverified cleanup, assert
that outcome, then dispose ONLY their synthetic locks/quarantine state. They do
not provide a production lock-stealing or recovery API.
"""
import ctypes as C
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from owned_process import Running, verify_attempt, AdapterError, SERIAL, INCOMPLETE_ATTEMPTS
from test_owned_process import binding, small_limits, SyntheticResources
from test_windows_job import FakeAPI, FakePipe, PipeKernel, AttributeKernel
import windows_job as W

class SlowPipe:
    def __init__(self,immediate=False): self.immediate=immediate; self.closed=False
    def read(self,size,cancel):
        if not self.immediate: cancel.wait()
        return b''
    def close(self): self.closed=True

class EndedProcess:
    kind='reviewer-mock-only';pid=123;tree_empty_verified=True
    def __init__(self,immediate_stdout=False,immediate_stderr=False):
        self.stdout=SlowPipe(immediate_stdout);self.stderr=SlowPipe(immediate_stderr)
    def poll(self):return 0
    def rss(self):return 0
    def stop_tree(self):pass
    def reap(self):return 0
    def close(self):self.stdout.close();self.stderr.close()

class FailureAPI(FakeAPI):
    def __init__(self,failed_handle=None,termination_failure=False):
        super().__init__(); self.failed_handle=failed_handle;self.termination_failure=termination_failure
    def close(self,handle):
        super().close(handle)
        if handle==self.failed_handle:raise OSError('injected owned CloseHandle failure')
    def terminate(self,job):
        super().terminate(job)
        if self.termination_failure:raise OSError('injected owned job termination failure')

class LifecycleRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='owned-v2-regression-');self.root=Path(self.temp.name)
        self.original_attempts=len(INCOMPLETE_ATTEMPTS)
        self.original_owners=len(W.INCOMPLETE_OWNERS);self.original_pipes=len(W.PENDING_PIPES)
    def tearDown(self):
        # Every launcher/pipe in this file is a pure mock. This cleanup is not
        # available through the adapter and cannot operate on real owned jobs.
        if SERIAL.locked():SERIAL.release()
        del INCOMPLETE_ATTEMPTS[self.original_attempts:]
        del W.INCOMPLETE_OWNERS[self.original_owners:]
        del W.PENDING_PIPES[self.original_pipes:]
        self.temp.cleanup()
    def run_mock(self,launcher,mode='jsonl'):
        return Running([sys.executable,'-c','pass'],self.root,
            small_limits(stdout_mode=mode,drain_seconds=.01),self.root/'attempt',binding(self.root),
            resources=SyntheticResources(),launcher=launcher)
    def assert_incomplete_stream(self,mode,stdout=False,stderr=False):
        process=EndedProcess(stdout,stderr);run=self.run_mock(lambda *args:process,mode)
        with self.assertRaises(AdapterError):
            with run:
                if mode=='jsonl':list(run.jsonl())
                else:run.wait()
        self.assertFalse(run.receipt['completed']);self.assertEqual(run.receipt['state'],'partial')
        self.assertIn(run.receipt['resource_stop_reason'],('incomplete_stream_drain','incomplete_stream_retention'))
        with self.assertRaises(AdapterError):verify_attempt(self.root/'attempt',require_completed=True)
        self.assertFalse(verify_attempt(self.root/'attempt')['completed'])
        self.assertTrue(process.stdout.closed);self.assertTrue(process.stderr.closed)
        self.assertFalse(SERIAL.locked());self.assertFalse((self.root/'owner.lock').exists())
    def test_f1_bytes_cancelled_stdout_and_stderr_not_success(self):self.assert_incomplete_stream('bytes')
    def test_f1_jsonl_cancelled_stderr_not_success(self):self.assert_incomplete_stream('jsonl',stdout=True)
    def test_f1_jsonl_cancelled_stdout_not_success(self):self.assert_incomplete_stream('jsonl',stderr=True)

    def constructor_failure(self,handle,pipe_factory=FakePipe,termination_failure=False):
        api=FailureAPI(handle,termination_failure)
        run=self.run_mock(lambda *args:W.WindowsProcess(*args,api=api,pipe_factory=pipe_factory))
        with self.assertRaises(W.WindowsLaunchError):
            with run:list(run.jsonl())
        self.assertTrue(run.receipt['started']);self.assertEqual(run.receipt['pid'],123)
        self.assertFalse(run.receipt['completed']);self.assertFalse(run.receipt['cleanup_complete'])
        self.assertIn(('terminate_job',1),api.events);self.assertIn(('active',1),api.events)
        self.assertIn(('close',1),api.events)
        self.assertTrue((self.root/'owner.lock').exists());self.assertTrue(SERIAL.locked())
        self.assertIn(run,INCOMPLETE_ATTEMPTS);self.assertIn(run.process,W.INCOMPLETE_OWNERS)
        with self.assertRaises(AdapterError):verify_attempt(self.root/'attempt',require_completed=True)
        # Every independent handle is attempted, even after an earlier failure.
        for expected in (1,2,3,4,12,13,14,15):self.assertIn(('close',expected),api.events)
        self.assertEqual(sum(e==('close',handle) for e in api.events),1)
        return api,run
    def test_f2_stdout_writer_close_failure_retains_actual_owner(self):self.constructor_failure(13)
    def test_f2_stderr_writer_close_failure_retains_actual_owner(self):self.constructor_failure(15)
    def test_f2_nul_close_failure_retains_actual_owner(self):self.constructor_failure(2)
    def test_f2_thread_close_failure_retains_actual_owner(self):self.constructor_failure(4)
    def test_f2_job_close_failure_attempts_remaining_cleanup(self):
        def broken(api,handle):raise RuntimeError('event construction failed')
        self.constructor_failure(1,broken)
    def test_f2_process_close_failure_attempts_remaining_cleanup(self):
        def broken(api,handle):raise RuntimeError('event construction failed')
        self.constructor_failure(3,broken)
    def test_f2_termination_failure_does_not_release_lock(self):self.constructor_failure(13,termination_failure=True)
    def test_f2_event_construction_failure_can_verify_full_cleanup(self):
        api=FakeAPI()
        def broken(api,handle):raise RuntimeError('event construction failed')
        run=self.run_mock(lambda *args:W.WindowsProcess(*args,api=api,pipe_factory=broken))
        with self.assertRaises(W.WindowsLaunchError):
            with run:list(run.jsonl())
        self.assertTrue(run.receipt['started']);self.assertTrue(run.receipt['cleanup_complete'])
        self.assertTrue(run.receipt['windows_job_empty_verified'])
        self.assertFalse(run.receipt['completed']);self.assertFalse(SERIAL.locked())
        self.assertFalse((self.root/'owner.lock').exists())
    def test_f2_second_reader_construction_failure_closes_first(self):
        api=FakeAPI();calls=[0]
        def second_fails(api,handle):
            calls[0]+=1
            if calls[0]==2:raise RuntimeError('second event construction failed')
            return FakePipe(api,handle)
        with self.assertRaises(W.WindowsLaunchError) as caught:
            W.WindowsProcess(['x'],'y',{},api=api,pipe_factory=second_fails)
        self.assertTrue(caught.exception.owned_process.constructor_cleanup_complete)
        self.assertEqual(sorted(e[1] for e in api.events if e[0]=='close'),[1,2,3,4,12,13,14,15])

    def test_f2_reader_close_failure_attempts_other_independent_closes(self):
        class BrokenReader(FakePipe):
            def close(self):
                self.api.close(self.handle)
                if self.handle==12:raise OSError('reader close failed')
                self.handle=None
        self.constructor_failure(13,BrokenReader)
    def test_f2_attribute_cleanup_failure_keeps_created_process_identity(self):
        api=FakeAPI();api.k=AttributeKernel();api.check=W.WinAPI.check
        def fail_delete(*args):raise OSError('attribute cleanup failed')
        api.k.DeleteProcThreadAttributeList=fail_delete
        api.create_in_job=W.WinAPI.create_in_job.__get__(api)
        run=self.run_mock(lambda *args:W.WindowsProcess(*args,api=api,pipe_factory=FakePipe))
        with self.assertRaises(W.WindowsLaunchError):
            with run:list(run.jsonl())
        self.assertTrue(run.receipt['started']);self.assertEqual(run.receipt['pid'],123)
        self.assertTrue(run.receipt['windows_job_empty_verified'])
        self.assertTrue(run.receipt['cleanup_complete']);self.assertFalse(SERIAL.locked())
        self.assertIn(('terminate_job',1),api.events)
    def test_f2_uncertain_prelaunch_setup_handle_retains_lock(self):
        api=FakeAPI()
        def bad_pipe():raise W.HandleSetupError(12,OSError('reader setup close failed'))
        api.pipe=bad_pipe
        run=self.run_mock(lambda *args:W.WindowsProcess(*args,api=api,pipe_factory=FakePipe))
        with self.assertRaises(W.WindowsLaunchError):
            with run:list(run.jsonl())
        self.assertFalse(run.receipt['started']);self.assertFalse(run.receipt['cleanup_complete'])
        self.assertTrue(SERIAL.locked());self.assertTrue((self.root/'owner.lock').exists())
        self.assertEqual(run.process.handles['uncertain_setup_0'],12)
        self.assertIn(('close',1),api.events)

    def pipe(self,kernel):
        api=W.WinAPI.__new__(W.WinAPI);api.k=kernel;api.close=lambda handle:kernel.events.append(('close',handle))
        pipe=W.WindowsPipe(api,11);pipe.cancellation_grace_seconds=.01
        return pipe
    def test_f3_failed_wait_cancels_and_observes_before_storage_release(self):
        kernel=PipeKernel(pending=True);kernel.WaitForSingleObject=lambda *args:0xFFFFFFFF
        pipe=self.pipe(kernel)
        with mock.patch.object(C,'get_last_error',lambda:kernel.error,create=True),self.assertRaises(OSError):
            pipe.read(64,threading.Event())
        self.assertIn('cancel',kernel.events);self.assertIn('result',kernel.events)
        self.assertLess(kernel.events.index('cancel'),kernel.events.index('result'))
        self.assertIsNone(pipe.pending);pipe.close()
        self.assertIn(('close',11),kernel.events);self.assertIn(('close',20),kernel.events)
    def pending_failure(self,cancel_failure=False,result_exception=False):
        kernel=PipeKernel(pending=True);kernel.WaitForSingleObject=lambda *args:0xFFFFFFFF
        def cancel(*args):
            kernel.events.append('cancel')
            if cancel_failure:raise OSError('cancel failed')
            return 1
        def result(*args):
            kernel.events.append('result')
            if result_exception:raise OSError('completion observation failed')
            kernel.error=W.ERROR_IO_INCOMPLETE;return 0
        kernel.CancelIoEx=cancel;kernel.GetOverlappedResult=result
        pipe=self.pipe(kernel)
        with mock.patch.object(C,'get_last_error',lambda:kernel.error,create=True),self.assertRaises(W.PendingReadError):
            pipe.read(64,threading.Event())
        self.assertIsNotNone(pipe.pending);self.assertIn(pipe,W.PENDING_PIPES)
        self.assertIn('cancel',kernel.events);self.assertIn('result',kernel.events)
        with self.assertRaises(W.PendingReadError):pipe.close()
        self.assertFalse(any(isinstance(e,tuple) and e[0]=='close' for e in kernel.events))
        return pipe,kernel
    def test_f3_failed_cancel_and_pending_completion_keep_storage(self):self.pending_failure(cancel_failure=True)
    def test_f3_pending_completion_timeout_keeps_storage(self):self.pending_failure()
    def test_f3_completion_api_exception_keeps_storage(self):self.pending_failure(result_exception=True)
    def test_f3_pending_read_reaches_supervisor_as_incomplete_cleanup(self):
        kernel=PipeKernel(pending=True);kernel.WaitForSingleObject=lambda *args:0xFFFFFFFF
        def result(*args):kernel.events.append('result');kernel.error=W.ERROR_IO_INCOMPLETE;return 0
        kernel.GetOverlappedResult=result
        pipe=self.pipe(kernel);process=EndedProcess(True,True);process.stdout=pipe
        run=self.run_mock(lambda *args:process)
        with mock.patch.object(C,'get_last_error',lambda:kernel.error,create=True),self.assertRaises(AdapterError):
            with run:list(run.jsonl())
        self.assertFalse(run.receipt['cleanup_complete']);self.assertFalse(run.receipt['completed'])
        self.assertIsNotNone(pipe.pending);self.assertIn(pipe,W.PENDING_PIPES)
        self.assertTrue(SERIAL.locked());self.assertTrue((self.root/'owner.lock').exists())
        self.assertIn(run,INCOMPLETE_ATTEMPTS)

if __name__=='__main__':unittest.main(verbosity=2)
