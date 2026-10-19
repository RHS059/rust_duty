"""Production-only source export/conversion. No control/oracle/parity stages."""
from __future__ import annotations
import argparse, sys, types
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
from common import *
APPROVED='b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
CANONICAL='d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab'

class File:
    def __init__(self,value):self.path=Path(value['path']);self.sha256=value['sha256']
    def verify(self):return pin(self.path,self.sha256)

class Context:
    def __init__(self,value):
        self.value=value;self.stage=value['stage'];self.index=value.get('index');self.output=ordinary(value['output']);self.binding=value['binding']
        self.cc=module("candidate_context",Path(value["roots"]["context_package"])/"candidate_context.py")
    def root(self,role):return ordinary(self.value['roots'][role],True)
    def pin(self,role):return File(self.value['files'][role])
    def frames(self):
        if self.stage=='block':
            lo=self.index*2048;hi=min(lo+2048,24320);return [1+i/256 for i in range(lo,hi+1)]
        return [1.]

def export_source(ctx,native,code):
    import bpy,numpy as np
    from mathutils import Matrix
    source=ctx.pin('generated_source').verify()
    need('FINISHED' in bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False),'source open failed')
    e=native.environment(ctx,bpy,np,Matrix);A=bpy.data.objects['Arms'];C=bpy.data.objects[native.CAMERA];S=bpy.context.scene
    need((S.render.fps,S.render.fps_base)==(60,1.),'approved source native clock differs')
    need(e['action_fingerprint'](bpy.data.actions[native.ACTION])==ctx.value['action_fingerprint'],'approved Action identity differs')
    e.update(A=A,C=C,S=S,P=ctx.output,FRAMES=[1.])
    code.execute('source_capture',e)
    try:
        code.execute('source_select',e)
        bpy.ops.object.select_all(action='DESELECT')
        for name in ['Arms',*native.SKINS,*native.ACTORS,native.CAMERA]:bpy.data.objects[name].select_set(True)
        bpy.context.view_layer.objects.active=A
        path=ctx.output/'animation.fbx';capacity(path,256*1024**2)
        result,_=e['export_exact_grid'](path,native.SETTINGS)
        need('FINISHED' in result and path.is_file() and 0<path.stat().st_size<=256*1024**2,'FBX export failed or exceeded output limit')
        return {'fbx':record(path)}
    finally:
        code.execute('source_restore',e)
        # The opened source remains read-only; no render/save or evaluated comparison.
        ctx.pin('generated_source').verify()

def run(value):
    ctx=Context(value);need(ctx.stage in ('export','geometry','block'),'unsupported production stage')
    need(ctx.stage!='block' or type(ctx.index) is int and 0<=ctx.index<12,'invalid conversion block')
    for ref in value['files'].values():pin(ref['path'],ref['sha256'])
    need(not ctx.output.exists(),'fresh production stage output required');capacity(ctx.output,288*1024**2);ctx.output.mkdir(parents=True)
    root=ctx.root('native_producer');loaded={}
    for name in ('pinned_code','stage_context','native_stages'):module(name,root/(name+'.py'),loaded)
    native=loaded['native_stages'];code=loaded['pinned_code']
    if ctx.stage=='export':payload=export_source(ctx,native,code)
    else:
        import bpy,numpy as np
        from mathutils import Matrix
        payload=native.conversion_stage(ctx,native.environment(ctx,bpy,np,Matrix))
    write(ctx.output/'conversion-result.json',{'stage':ctx.stage,'index':ctx.index,'payload':payload})
    return payload

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);run(read(pin(a.config,a.sha256)))
if __name__=='__main__':main()
