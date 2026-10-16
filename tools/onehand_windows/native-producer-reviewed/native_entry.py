"""Actual native entry; use only the pinned owned-process launcher after admission."""
import argparse,json,os,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).absolute().parent
# Only the current reviewed source package is inserted; no frozen program imports.
sys.path.insert(0,str(HERE))
from pinned_code import file_sha,require
from stage_context import StageContext,capacity,write_new,MIB
from planner import native_argv,output_cap
from admission import verify_package,host_build,validate_dependencies,validate_payload
from transport_binding import verify_transport


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--context',required=True,type=Path);p.add_argument('--context-sha256',required=True);p.add_argument('--context-package',required=True,type=Path);p.add_argument('--producer-pins-sha256',required=True)
    a=p.parse_args(argv);verify_package(a.producer_pins_sha256)
    ctx=StageContext.read(a.context,a.context_sha256,a.context_package)
    require(ctx.raw['dependencies']['producer_pins_sha256']==a.producer_pins_sha256,'caller producer pin differs')
    ctx.host.require_current_host();ctx.verify_files();verify_transport(ctx,production=True);host_build(ctx,native=True,current=True)
    require('--factory-startup' in sys.argv and '--disable-autoexec' in sys.argv,'safe native flags required')
    # A direct manual native invocation cannot bypass reviewed bounded transport.
    started=ctx.transport_output/'started.json';deadline=time.monotonic()+2
    while not started.exists() and time.monotonic()<deadline:time.sleep(.01)
    rec=ctx.cc.strict_json(started)
    require(rec['pid']==os.getpid() and rec['backend']=='windows-job-list-overlapped-v2' and rec['command']==native_argv(ctx),'actual owned native process binding differs')
    require(rec['host_binding']['context_sha256']==ctx.context_sha256 and rec['host_binding']['build_sha256']==ctx.host.build_sha256,'owned process context differs')
    require(ctx.owner_lock.is_file() and not ctx.output.exists(),'live owner/fresh output required')
    validate_dependencies(ctx);capacity(ctx.output,output_cap(ctx));ctx.output.parent.mkdir(parents=True,exist_ok=True);ctx.output.mkdir()
    try:
        from native_stages import perform
        payload=perform(ctx);validate_payload(ctx,payload)
        ctx.verify_files()
        files={}
        for path in sorted(ctx.output.rglob('*')):
            ctx.cc.ordinary(path,existing=True)
            if path.is_file():files[path.relative_to(ctx.output).as_posix()]={'sha256':file_sha(path),'bytes':path.stat().st_size}
        require(sum(r['bytes'] for r in files.values())<=output_cap(ctx),'native output cap exceeded')
        result={'schema':'rust-duty-windows-native-stage/v1','stage':ctx.stage,'index':ctx.index,'context_sha256':ctx.context_sha256,
                'context_file_sha256':file_sha(ctx.path),'binding':ctx.binding,'output_files':files,'payload':payload,'passed':True,
                'source_saved':False,'rendered':False,'cross_platform_float64_equality_proved':False,'runtime_equivalence_proved':False,
                'artistic_approval':False,'activation_authorized':False}
        write_new(ctx.output/'receipt.json',result);capacity(ctx.output,0)
        print(json.dumps({'native_stage':ctx.stage,'receipt_sha256':file_sha(ctx.output/'receipt.json'),'passed':True}),flush=True)
    except BaseException as exc:
        # Hash-only bounded failure summary; raw failed evidence stays local.
        failure={'schema':'rust-duty-windows-native-failure/v1','stage':ctx.stage,'context_sha256':ctx.context_sha256,'binding':ctx.binding,
                 'exception_type':type(exc).__name__,'passed':False,'private_raw_survival_after_runner_teardown_guaranteed':False}
        if not (ctx.output/'failure.json').exists():write_new(ctx.output/'failure.json',failure)
        raise

if __name__=='__main__':main(sys.argv[sys.argv.index('--')+1:])
