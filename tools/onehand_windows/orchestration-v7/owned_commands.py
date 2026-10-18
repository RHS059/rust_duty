"""Controller calls the unchanged owned-process v2 for every executable leaf.

Build commands own their descendant tree. RSS remains sampled direct-child RSS,
not a claimed aggregate Cargo/rustc/linker memory bound.
"""
from pathlib import Path
import dataclasses
from workflow_core import *

def transport_environment_binding(adapter,environment):
    """Use the frozen adapter's newline-terminated canonical transport protocol.

    Controller/config/build digests intentionally use a different, unchanged
    encoding. Only the receipt-facing environment fingerprint belongs here.
    """
    return {'environment_sha256':adapter.digest(environment),'environment_keys':sorted(environment)}

class Commands:
    def __init__(self,adapter,host,candidate,environment,process_validator):
        self.adapter=adapter;self.host=host;self.candidate=ordinary(candidate)
        self.environment=dict(environment);self.process_validator=process_validator
        require(type(environment) is dict and all(type(k) is str and type(v) is str for k,v in environment.items()),'explicit string environment')
        require(not ({k.upper() for k in environment}&{'PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','VRVIEW_TOOLS_PATH','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','VR_WEAPON_ASSET'}),'unreviewed executable/module override')
    def run(self,label,argv,cwd,*,environment=None,reserve=0,stdout_cap=4*1024**2):
        require(type(argv) is list and argv and all(type(v) is str for v in argv),'explicit argv list')
        executable=record(argv[0]);env=self.environment if environment is None else dict(environment)
        target=self.candidate/'process'/label;require(not target.exists(),'fresh owned command required')
        self.candidate.mkdir(parents=True,exist_ok=True);target.parent.mkdir(parents=True,exist_ok=True)
        lock=self.candidate.parent.parent/'native-owner.lock';capacity(target,reserve+stdout_cap+16*1024**2)
        context={'schema':'rust-duty-onehand-controller-command/v1','label':label,'argv':argv,'cwd':str(ordinary(cwd,True)),'executable':executable,'environment_sha256':digest(env),'host':self.host}
        context_file=write_new(self.candidate/'contexts'/(label+'-command.json'),context)
        binding=self.adapter.HostBinding(runner_id=self.host['runner_id'],run_id=self.host['run_id'],build_sha256=self.host['build_sha256'],context_sha256=digest(context),expected_host={k:self.host[k] for k in ('system','release','version','machine')},environment=env,owner_lock=str(lock))
        limits=self.adapter.Limits(stdout_mode='bytes',max_stdout_bytes=stdout_cap,max_stderr_bytes=1024**2)
        with self.adapter.OwnedProcess.run(argv,ordinary(cwd,True),limits,target,binding) as process:process.wait()
        result=self.adapter.verify_attempt(target,require_completed=True)
        require(result['completed'] is True and result['windows_job_empty_verified'] is True,'actual completed Windows owned command required')
        require(result['command']==argv and result['cwd']==str(cwd),'owned command differs')
        pin(argv[0],executable['sha256'])
        expected_host={'runner_id':self.host['runner_id'],'run_id':self.host['run_id'],'build_sha256':self.host['build_sha256'],'context_sha256':digest(context),'observed_host':{k:self.host[k] for k in ('system','release','version','machine')},'owner_lock':str(lock),**transport_environment_binding(self.adapter,env)}
        self.process_validator(self.adapter,target,{'command':argv,'cwd':str(cwd),'host_binding':expected_host,'limits':dataclasses.asdict(limits),'supervisor_python':record(sys.executable),'executable':executable,'rows':0})
        return {'context':context_file,'terminal':file_pin(target/'terminal.json'),'stdout':record(target/'stdout.bin'),'stderr':record(target/'stderr.bin'),'value':result,'command':argv,'environment_sha256':digest(env)}
