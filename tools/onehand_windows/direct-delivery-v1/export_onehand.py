"""Explicit optional export command, separate from normal existing-byte delivery."""
from __future__ import annotations
import argparse,sys,shutil
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
from common import *
from owned_commands import Commands,clean_environment
import runtime_binding
HERE=Path(__file__).absolute().parent

def export(inputs,work,blender,commands):
    inputs=ordinary(inputs,True);work=ordinary(work);work.mkdir(parents=True,exist_ok=True)
    source=work/'regenerated-onehand-v6.blend';replay=work/'replay-receipt.json'
    producer=inputs/'source-producer/onehand_v6_source_native.py';delta=inputs/'original-source/original-delta.json'
    prefix=[str(blender),'--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python']
    commands.run('source-replay',prefix+[str(producer),'--','replay','--base',str(inputs/'existing-public/r3.blend'),'--delta',str(delta),'--delta-sha256',sha(delta),'--output',str(source),'--receipt',str(replay)],work,reserve=96*1024**2)
    replay_value=read(replay)
    roots={'audited_source':str(inputs/'audited'),'native_producer':str(inputs/'native-producer-reviewed'),'context_package':str(inputs/'context-v3')}
    files={'generated_source':record(source),'canonical':record(inputs/'existing-public/locomotion.vra')}
    binding={'generated_source_sha256':sha(source),'approved_source_sha256':runtime_binding.APPROVED}
    def stage(name,index=None):
        label=name if index is None else name+'-'+str(index);output=work/'native'/label
        value={'stage':name,'index':index,'output':str(output),'roots':roots,'files':dict(files),'binding':dict(binding),'action_fingerprint':runtime_binding.FINGERPRINT}
        path=work/'contexts'/(label+'.json');ref=write(path,value)
        commands.run('onehand-'+label,prefix+[str(HERE/'native_export.py'),'--','--config',str(path),'--sha256',ref['sha256']],work,reserve=288*1024**2)
        return output
    exported=stage('export');fbx=exported/'animation.fbx';files['actual_fbx']=record(fbx);binding['actual_fbx_sha256']=sha(fbx)
    geometry=stage('geometry')/'runtime'
    for role,name in (('geometry','geometry-metadata.json'),('vrs','asset.vrs'),('vrm','asset.vrm')):files[role]=record(geometry/name)
    blocks=[stage('block',i)/'block/receipt.json' for i in range(12)]
    loaded={};module('candidate_context',inputs/'context-v3/candidate_context.py',loaded)
    loader=module('pinned_assembler',inputs/'context-v3/pinned_assembler.py',loaded)
    a=loader.load_assembler(inputs/'audited/onehand-runtime-20261016-r2/runtime-conversion-v2',inputs/'audited/onehand-runtime-20261016/importer-patch/tools')
    runtime=work/'runtime';runtime.mkdir()
    contract=a.StreamContract(source_sha256=sha(source),fbx_sha256=sha(fbx),canonical_sha256=sha(inputs/'existing-public/locomotion.vra'))
    a.assemble_stream(geometry/'geometry-metadata.json',geometry/'asset.vrs',geometry/'asset.vrm',blocks,runtime/'asset.vra',contract=contract)
    for ext in ('vrs','vrm'):runtime_binding.replace_file(geometry/('asset.'+ext),runtime/('asset.'+ext))
    return runtime,source,fbx

def main():
    p=argparse.ArgumentParser()
    for key in ('inputs','work','blender','root'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();need(not a.work.exists(),'fresh optional export directory required');a.work.mkdir(parents=True)
    commands=Commands(a.inputs/'process-v2',a.work,clean_environment())
    runtime,source,fbx=export(a.inputs,a.work,a.blender,commands)
    runtime_binding.install(a.root,runtime,source,fbx)
if __name__=='__main__':main()
