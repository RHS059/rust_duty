"""Serial, bounded existing Windows Job transport for actual delivery commands."""
import os, sys
from pathlib import Path
from common import *

class Commands:
    def __init__(self,adapter_root,work,environment):
        loaded={};module('windows_job',Path(adapter_root)/'windows_job.py',loaded)
        self.adapter=module('owned_process',Path(adapter_root)/'owned_process.py',loaded)
        self.work=ordinary(work);self.environment=dict(environment);self.host=self.adapter.observed_host()
        need(self.host['system']=='Windows','Windows game delivery requires Windows host')
        self.run_id='run-'+os.environ.get('GITHUB_RUN_ID','local')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','1')
        self.host_sha=digest(self.host)
    def run(self,label,argv,cwd,*,environment=None,reserve=0,stdout_cap=4*1024**2):
        need(label and all(c.isalnum() or c in '-_' for c in label),'invalid process label')
        argv=list(map(str,argv));env=self.environment if environment is None else environment
        self.last_command={'stage':label,'argv':argv}
        out=self.work/'process'/label;need(not out.exists(),'process output must be fresh');capacity(out,reserve+stdout_cap)
        out.parent.mkdir(parents=True,exist_ok=True)
        write(self.work/'commands'/(label+'.json'),{'stage':label,'argv':argv})
        executable=record(argv[0]);context={'argv':argv,'cwd':str(ordinary(cwd,True)),'executable':executable}
        binding=self.adapter.HostBinding('direct-delivery',self.run_id,self.host_sha,self.host,env,str(self.work/'native-owner.lock'),digest(context))
        limits=self.adapter.Limits(stdout_mode='bytes',max_stdout_bytes=stdout_cap,max_stderr_bytes=1024**2)
        try:
            with self.adapter.OwnedProcess.run(argv,ordinary(cwd,True),limits,out,binding) as process:process.wait()
        except Exception as error:
            if label in ('materialize-existing','game-build','updater-fetch','updater-notices','game-package'):
                stderr=out/'stderr.bin';detail=''
                if stderr.is_file():
                    with stderr.open('rb') as stream:
                        stream.seek(max(0,stderr.stat().st_size-3072));detail=stream.read(3072).decode('utf-8','replace')
                raise RuntimeError(label+' failed: '+str(error)[:512]+('\n'+detail if detail else '')) from error
            raise
        terminal=self.adapter.verify_attempt(out,require_completed=True)
        need(terminal['completed'] is True and terminal['windows_job_empty_verified'] is True,'command failed or descendants still active')
        pin(argv[0],executable['sha256'])
        return {'stdout':record(out/'stdout.bin'),'stderr':record(out/'stderr.bin'),'terminal':record(out/'terminal.json')}

def clean_environment():
    # Preserve MSVC/SDK and operating-system paths, never arbitrary executable overrides or credentials.
    allowed={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','TEMP','TMP','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','VCTOOLSINSTALLDIR','VCINSTALLDIR','VSINSTALLDIR','WINDOWSSDKDIR','WINDOWSSDKVERSION','WINDOWSSDKBINPATH','WINDOWSSDKVERBINPATH','UNIVERSALCRTSDKDIR','UCRTVERSION','INCLUDE','LIB','LIBPATH','VSCMD_ARG_TGT_ARCH','VSCMD_ARG_HOST_ARCH','PROCESSOR_ARCHITECTURE','PROCESSOR_ARCHITEW6432','CARGO_HOME','RUSTUP_HOME','GITHUB_ACTIONS','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA'}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='1',CARGO_TERM_COLOR='never')
    return env
