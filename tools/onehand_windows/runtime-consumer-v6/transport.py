"""Actual leaf-sampler OwnedProcess transport; no selectors or POSIX pipes here.

Frozen v2 can be integrity-loaded for source tests. This does not override the
RuntimeContext production gate or constitute independent transport admission.
"""
from pathlib import Path
import dataclasses,math
import pinned_math as p
from runtime_context import record,pe_x64
V2_PINS_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
V2_FILES={'owned_process.py':'256125ea044c738ac316da841a5acad9c39b1fc2b1666cc4a09ce81828bd191e','windows_job.py':'d628c4f7d3136dde11cf6c9d5ba35f3d12302bfd2522918fe1f0229a40f1ba1e'}
def load(package):
    package=Path(package);p.pin(package/'PINS.json',V2_PINS_SHA);manifest=p.read(package/'PINS.json')
    for name,row in manifest['files'].items():
        p.require(Path(name).name==name,'unsafe process pin');p.pin(package/name,row['sha256'])
    for n,v in V2_FILES.items():p.pin(package/n,v)
    known={};known['windows_job']=p.private_module('windows_job',package/'windows_job.py',known)
    return p.private_module('owned_process',package/'owned_process.py',known)

def command(ctx,frames):
    p.require(frames and len(frames)<=64 and all(type(f) is float and math.isfinite(f) and 1<=f<=96 for f in frames),'bounded ordered source frames required')
    p.require(frames==sorted(set(frames)),'duplicate/reordered sampler times')
    return [str(ctx.pin('sampler').path),str(ctx.pin('vra').path),p.ACTION,*[repr((f-1)/60) for f in frames],'--clamp']

def limits(mod,rows):
    # Preserve original 16 MiB row, 3 GiB own-child, 0.2 s, 1,800 s and 1 GiB
    # floor. stdout bounded by rows, never a complete unbounded pipe buffer.
    return mod.Limits(max_rows=rows,max_stdout_bytes=min(256*1024**2,rows*16*1024**2),max_row_bytes=16*1024**2,queue_rows=2,queue_bytes=32*1024**2)

def binding(ctx,environment):
    return {'runner_id':ctx.host.runner_id,'run_id':ctx.host.run_id,'build_sha256':ctx.pin('rust_build').sha256,'expected_host':ctx.host.expected_host,'environment':dict(environment),'owner_lock':str(ctx.owner_lock),'context_sha256':ctx.context_sha256}

def exact_rows(rows,count,consume):
    result=[]
    for i in range(count):
        row=next(rows,None);p.require(row is not None,'Rust sampler ended early');p.require(type(row) is dict,'Rust row must be object');result.append(consume(i,row))
    p.require(next(rows,None) is None,'Rust sampler emitted extra row');return result

def verify(ctx,frames,attempt_root,environment,terminal_sha=None):
    # One shared reviewed reconstruction for native and actual-Rust processes.
    # Hash/completion checks alone do not reconcile predecessor/resource facts.
    import evidence
    mod=load(ctx.root('process_adapter'));root=ctx.cc.ordinary(attempt_root,existing=True)
    p.require(root.is_relative_to(ctx.candidate_root/'process'),'sampler process outside candidate')
    p.pin(root/'terminal.json',ctx.cc.sha(terminal_sha))
    host=ctx.cc.strict_json(ctx.pin('host_binding').verify())
    supervisor=ctx.cc.FilePin.parse('actual supervisor Python',host['tools']['python']);supervisor.verify()
    sampler=ctx.pin('sampler');sampler.verify()
    expected={'command':command(ctx,frames),'cwd':str(ctx.candidate_root),
              'host_binding':mod.HostBinding(**binding(ctx,environment)).record(),
              'limits':dataclasses.asdict(limits(mod,len(frames))),'rows':len(frames),
              'supervisor_python':{'path':str(supervisor.path),'sha256':supervisor.sha256,'bytes':supervisor.path.stat().st_size},
              'executable':{'path':str(sampler.path),'sha256':sampler.sha256,'bytes':sampler.path.stat().st_size}}
    verified=evidence.producer(ctx).verify_completed_process(mod,root,expected)
    supervisor.verify();sampler.verify()
    # Derived data is stored only in the runtime receipt, never rewritten into
    # the externally pinned OwnedProcess terminal. Gaps are observed coverage.
    return {**verified['record'],'retained_process_validation':verified['resources']}

def run(ctx,frames,label,environment,consume):
    # No externally injectable runner/launcher. Synthetic tests never invoke run.
    ctx.require_production();pe_x64(ctx.pin('sampler').verify())
    mod=load(ctx.root('process_adapter'));ctx.cc.identifier(label,'sampler stage');root=ctx.candidate_root/'process'/('runtime-'+label)
    ctx.cc.ordinary(root);p.require(not root.exists(),'preserve previous sampler attempt')
    process=mod.OwnedProcess.run(command(ctx,frames),ctx.candidate_root,limits(mod,len(frames)),root,mod.HostBinding(**binding(ctx,environment)))
    with process as running:results=exact_rows(running.jsonl(),len(frames),consume)
    terminal=record(root/'terminal.json');value=verify(ctx,frames,root,environment,terminal['sha256']);return results,{'terminal':terminal,'record':value}
