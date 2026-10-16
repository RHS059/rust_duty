"""Win32 ABI/ownership/overlapped API mock tests; these do not execute Windows."""
import ctypes as C
from types import SimpleNamespace
import threading
import unittest
from unittest import mock
import windows_job as W

class FakePipe:
    def __init__(self, api, handle): self.api,self.handle=api,handle
    def close(self): self.api.close(self.handle); self.handle=None

class FakeAPI:
    def __init__(self, failure=None, associated=True, inherited=True):
        self.events=[]; self.next=10; self.failure=failure
        self.associated,self.inherited=associated,inherited
    def inherited_job(self): self.events.append(('parent_job',)); return self.inherited
    def create_job(self): self.events.append(('job',1)); return 1
    def pipe(self):
        self.next+=2; self.events.append(('pipe',self.next,self.next+1)); return self.next,self.next+1
    def nul(self): self.events.append(('nul',2)); return 2
    def create_in_job(self,*args,adopt=None):
        self.events.append(('atomic_create',args))
        if self.failure: raise OSError('nested job or creation refused')
        info=SimpleNamespace(process=3,thread=4,pid=123)
        if adopt is not None:adopt(info)
        return info
    def in_job(self,process,job): self.events.append(('membership',process,job)); return self.associated
    def close(self,handle):
        if handle: self.events.append(('close',handle))
    def terminate(self,job): self.events.append(('terminate_job',job))
    def terminate_process(self,process): self.events.append(('terminate_child',process))
    def active_processes(self,job): self.events.append(('active',job)); return 0
    def poll(self,process): return 7
    def rss(self,process): return 1024

class OwnershipMocks(unittest.TestCase):
    def test_atomic_job_before_execution_and_only_own_job_stopped(self):
        api=FakeAPI(); child=W.WindowsProcess(['C:\\python.exe','-c','pass'],'C:\\work',{},api=api,pipe_factory=FakePipe)
        names=[e[0] for e in api.events]
        self.assertLess(names.index('job'),names.index('atomic_create'))
        self.assertLess(names.index('atomic_create'),names.index('membership'))
        self.assertTrue(child.parent_in_job); self.assertEqual(child.pid,123)
        child.stop_tree(); self.assertEqual(child.reap(),7); self.assertTrue(child.tree_empty_verified); child.close()
        self.assertEqual([e for e in api.events if e[0]=='terminate_job'],[('terminate_job',1)])
        self.assertEqual(sum(e==('close',1) for e in api.events),1)
        self.assertNotIn(('terminate_child',3),api.events)
        closed=[e[1] for e in api.events if e[0]=='close']
        self.assertEqual(sorted(closed),[1,2,3,4,12,13,14,15])

    def test_rejected_nested_assignment_no_breakaway_or_retry(self):
        api=FakeAPI(failure=True)
        with self.assertRaises(OSError): W.WindowsProcess(['x'],'y',{},api=api,pipe_factory=FakePipe)
        self.assertEqual(sum(e[0]=='atomic_create' for e in api.events),1)
        self.assertIn(('close',1),api.events)
        self.assertFalse(any(e[0].startswith('terminate') for e in api.events))
        self.assertEqual(sorted(e[1] for e in api.events if e[0]=='close'),[1,2,12,13,14,15])

    def test_failed_membership_stops_exact_created_child_and_job(self):
        api=FakeAPI(associated=False)
        with self.assertRaises(W.WindowsLaunchError): W.WindowsProcess(['x'],'y',{},api=api,pipe_factory=FakePipe)
        self.assertIn(('terminate_child',3),api.events); self.assertIn(('terminate_job',1),api.events)
        self.assertIn(('close',1),api.events)

    def test_reader_construction_failure_still_closes_job(self):
        api=FakeAPI()
        def broken(api,handle): raise RuntimeError('synthetic event creation failure')
        with self.assertRaises(W.WindowsLaunchError): W.WindowsProcess(['x'],'y',{},api=api,pipe_factory=broken)
        self.assertIn(('terminate_job',1),api.events)
        self.assertEqual(sorted(e[1] for e in api.events if e[0]=='close'),[1,2,3,4,12,13,14,15])

    def test_close_job_precedes_problematic_pipe_close(self):
        api=FakeAPI(); child=W.WindowsProcess(['x'],'y',{},api=api,pipe_factory=FakePipe)
        def broken(): raise OSError('pipe close failed')
        child.stdout.close=broken
        with self.assertRaises(OSError): child.close()
        self.assertIn(('close',1),api.events); self.assertIn(('close',3),api.events); self.assertIn(('close',14),api.events)

    def test_64bit_structure_layout(self):
        if C.sizeof(C.c_void_p)!=8: self.skipTest('64-bit ABI layout')
        for structure,expected in [(W.Startup,104),(W.StartupEx,112),(W.ProcessInfo,24),
            (W.BasicLimits,64),(W.ExtendedLimits,144),(W.MemoryStatus,64),(W.ProcessMemory,72),
            (W.Overlapped,32),(W.JobAccounting,48)]:
            self.assertEqual(C.sizeof(structure),expected,structure.__name__)

class AttributeKernel:
    def __init__(self): self.events=[]
    def InitializeProcThreadAttributeList(self,storage,count,flags,size):
        self.events.append(('init',bool(storage),count)); size._obj.value=128; return bool(storage)
    def UpdateProcThreadAttribute(self,storage,flags,key,value,size,previous,returned):
        self.events.append(('attribute',key,list(value))); return 1
    def CreateProcessW(self,exe,command,pa,ta,inherit,flags,env,cwd,startup,info):
        self.events.append(('create',exe,command.value,inherit,flags,cwd,startup._obj.startup.cb))
        info._obj.process=3; info._obj.thread=4; info._obj.pid=123; return 1
    def DeleteProcThreadAttributeList(self,storage): self.events.append(('delete',))

class APIMocks(unittest.TestCase):
    def test_exact_handle_list_job_list_and_flags(self):
        api=W.WinAPI.__new__(W.WinAPI); api.k=AttributeKernel()
        argv=['C:\\has space\\python.exe','a b','quoted"arg','trailing\\']
        result=api.create_in_job(1,argv,'C:\\work',{'SystemRoot':'C:\\Windows'},2,13,15)
        self.assertEqual(result.pid,123)
        self.assertIn(('attribute',W.JOB_LIST,[1]),api.k.events)
        self.assertIn(('attribute',W.HANDLE_LIST,[2,13,15]),api.k.events)
        create=[e for e in api.k.events if e[0]=='create'][0]
        self.assertEqual(create[1],argv[0]); self.assertEqual(create[2],W.subprocess.list2cmdline(argv))
        self.assertTrue(create[3]); self.assertTrue(create[4]&0x80000); self.assertFalse(create[4]&0x1000000)
        self.assertEqual(api.k.events[-1],('delete',))

    def test_windows_exit_259_is_exit_when_handle_signalled(self):
        api=W.WinAPI.__new__(W.WinAPI)
        def code(handle,out): out._obj.value=259; return 1
        api.k=SimpleNamespace(WaitForSingleObject=lambda *args:W.WAIT_OBJECT_0,GetExitCodeProcess=code)
        self.assertEqual(api.poll(3),259)
        api.k.WaitForSingleObject=lambda *args:W.WAIT_TIMEOUT
        self.assertIsNone(api.poll(3))

    def test_available_memory_and_working_set_field(self):
        api=W.WinAPI.__new__(W.WinAPI)
        def available(out): out._obj.available_phys=123456; return 1
        def rss(handle,out,size): out._obj.working_set=654321; return 1
        api.k=SimpleNamespace(GlobalMemoryStatusEx=available);api.p=SimpleNamespace(GetProcessMemoryInfo=rss)
        self.assertEqual(api.available(),123456); self.assertEqual(api.rss(3),654321)

class PipeKernel:
    def __init__(self,pending=False,cancelled=False,zero_first=False):
        self.events=[]; self.pending=pending; self.cancelled=cancelled; self.zero_first=zero_first
        self.error=W.ERROR_IO_PENDING; self.waits=0; self.reads=0
    def CreateEventW(self,*args): return 20
    def ResetEvent(self,*args): return 1
    def ReadFile(self,handle,buffer,count,out,operation):
        assert out is None
        self.buffer=buffer; self.reads+=1; self.events.append('read')
        C.memmove(buffer,b'abc',3)
        return not self.pending
    def WaitForSingleObject(self,*args):
        self.waits+=1
        return W.WAIT_TIMEOUT if self.cancelled and self.waits==1 else W.WAIT_OBJECT_0
    def CancelIoEx(self,*args): self.events.append('cancel'); return 1
    def GetOverlappedResult(self,handle,operation,got,wait):
        self.events.append('result')
        if self.cancelled: self.error=W.ERROR_OPERATION_ABORTED; return 0
        got._obj.value=0 if self.zero_first and self.reads==1 else 3; return 1

class PipeMocks(unittest.TestCase):
    def pipe(self,kernel):
        api=W.WinAPI.__new__(W.WinAPI); api.k=kernel; api.close=lambda handle:None
        return W.WindowsPipe(api,11)
    def test_immediate_overlapped_result(self):
        kernel=PipeKernel(); pipe=self.pipe(kernel)
        self.assertEqual(pipe.read(64,threading.Event()),b'abc'); self.assertIn('result',kernel.events)
    def test_pending_overlapped_result(self):
        kernel=PipeKernel(pending=True); pipe=self.pipe(kernel)
        with mock.patch.object(C,'get_last_error',lambda:kernel.error,create=True):
            self.assertEqual(pipe.read(64,threading.Event()),b'abc')
    def test_cancel_does_not_free_before_completion(self):
        kernel=PipeKernel(pending=True,cancelled=True); pipe=self.pipe(kernel); cancel=threading.Event()
        # Set cancellation after read has entered, matching a monitor shutdown.
        original=kernel.ReadFile
        def read(*args): cancel.set(); return original(*args)
        kernel.ReadFile=read
        with mock.patch.object(C,'get_last_error',lambda:kernel.error,create=True):
            self.assertEqual(pipe.read(64,cancel),b'')
        self.assertLess(kernel.events.index('cancel'),kernel.events.index('result'))
    def test_zero_write_not_eof(self):
        kernel=PipeKernel(zero_first=True); pipe=self.pipe(kernel)
        self.assertEqual(pipe.read(64,threading.Event()),b'abc'); self.assertEqual(kernel.reads,2)

if __name__=='__main__': unittest.main(verbosity=2)
