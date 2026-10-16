"""Single actual Blender leaf under the reviewed owned-process supervisor.

No retry, no shell command, no global process kill, no asset upload. Production
requires admitted Windows transport smoke, real authored input and host evidence.
"""
import argparse,json,sys
from pathlib import Path
from pinned_code import HERE,require,file_sha
from stage_context import StageContext,capacity,write_new
from planner import plan,native_argv,output_cap,process_limits
from admission import verify_package,host_build,validate_dependencies,verify_stage
from transport_binding import verify_transport


def launch(ctx,environment):
    verify_package(ctx.raw['dependencies']['producer_pins_sha256']);ctx.validate(fresh=True);ctx.host.require_current_host();ctx.verify_files()
    adapter=verify_transport(ctx,production=True);host=host_build(ctx,current=True);validate_dependencies(ctx)
    require(type(environment) is dict,'explicit bounded environment required')
    # Do not inherit alternate module/addon/config lookup from ambient host state.
    require(not ({k.upper() for k in environment}&{'PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','VRVIEW_TOOLS_PATH'}),'unreviewed module lookup environment')
    require(adapter.digest(environment)==host['native_environment_sha256'] and sorted(environment)==host['native_environment_keys'],'host-pinned native environment differs')
    capacity(ctx.output,output_cap(ctx)+16*1024**2)
    ctx.candidate_root.mkdir(parents=True,exist_ok=True);ctx.output.parent.mkdir(parents=True,exist_ok=True);ctx.transport_output.parent.mkdir(parents=True,exist_ok=True)
    binding=adapter.HostBinding(runner_id=ctx.host.runner_id,run_id=ctx.host.run_id,build_sha256=ctx.host.build_sha256,
        expected_host=ctx.host.expected_host,environment=environment,owner_lock=str(ctx.owner_lock),context_sha256=ctx.context_sha256)
    limits=process_limits(adapter)
    with adapter.OwnedProcess.run(native_argv(ctx),ctx.candidate_root,limits,ctx.transport_output,binding) as process:
        process.wait()
    return verify_stage(ctx.path,file_sha(ctx.path),ctx.root('context_package'),file_sha(ctx.output/'receipt.json'),file_sha(ctx.transport_output/'terminal.json'))


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--context',required=True,type=Path);p.add_argument('--context-sha256',required=True);p.add_argument('--context-package',required=True,type=Path)
    p.add_argument('--producer-pins-sha256',required=True);p.add_argument('--environment',required=True,type=Path);p.add_argument('--environment-sha256',required=True)
    a=p.parse_args(argv);verify_package(a.producer_pins_sha256);ctx=StageContext.read(a.context,a.context_sha256,a.context_package)
    require(ctx.raw['dependencies']['producer_pins_sha256']==a.producer_pins_sha256,'caller package pin differs')
    require(file_sha(a.environment)==ctx.cc.sha(a.environment_sha256),'explicit environment pin differs')
    result=launch(ctx,ctx.cc.strict_json(a.environment));print(json.dumps({'passed':result['passed'],'stage':result['stage'],'receipt_sha256':file_sha(ctx.output/'receipt.json'),'retained_process_validation':result['retained_process_validation']}))
if __name__=='__main__':main()
