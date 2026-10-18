"""Safe argv/planner; planning has no Blender/Windows/subprocess side effects."""
import argparse,dataclasses,json,sys
from pathlib import Path
from pinned_code import HERE,file_sha,require
from stage_context import StageContext
SOURCE_CAPS={'export':288,'control-export':288,'geometry':224,'block':16,'control-full':16}

def output_cap(ctx):return SOURCE_CAPS.get(ctx.stage,32)*1024**2

def native_argv(ctx):
    host=ctx.cc.strict_json(ctx.pin('host_binding').verify())
    blender=ctx.cc.FilePin.parse('blender',host['tools']['blender'])
    return [str(blender.path),'--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python',
            str(HERE/'native_entry.py'),'--','--context',str(ctx.path),'--context-sha256',file_sha(ctx.path),
            '--context-package',str(ctx.root('context_package')),'--producer-pins-sha256',ctx.raw['dependencies']['producer_pins_sha256']]

def process_limits(adapter):
    """Single exact launcher/admission limits constructor; unchanged v2 caps."""
    return adapter.Limits(stdout_mode='bytes',max_stdout_bytes=4*1024**2,max_stderr_bytes=1024**2)

def plan(ctx):
    return {'schema':'rust-duty-windows-native-plan/v1','stage':ctx.stage,'index':ctx.index,'context_sha256':ctx.context_sha256,
            'context_file_sha256':file_sha(ctx.path),'binding':ctx.binding,'argv':native_argv(ctx),'cwd':str(ctx.candidate_root),
            'output':str(ctx.output),'process_output':str(ctx.transport_output),'owner_lock':str(ctx.owner_lock),
            'output_cap_bytes':output_cap(ctx),'frames':ctx.frames(),'limits':{'rss_bytes':3*1024**3,'initial_available_bytes':3*1024**3+512*1024**2,
            'disk_floor_bytes':1024**3,'sample_seconds':.2,'deadline_seconds':1800.,'stdout_mode':'bytes','max_stdout_bytes':4*1024**2,'max_stderr_bytes':1024**2},
            'will_launch':False,'windows_execution_proved':False,'production_admitted':False}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--context',required=True,type=Path);p.add_argument('--context-sha256',required=True);p.add_argument('--context-package',required=True,type=Path)
    a=p.parse_args(argv);ctx=StageContext.read(a.context,a.context_sha256,a.context_package);print(json.dumps(plan(ctx),indent=2))
if __name__=='__main__':main()
