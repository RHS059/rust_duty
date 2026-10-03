#!/usr/bin/env python3
"""Rebuild authored walk through Blender→FBX→runtime; require native Rust parity."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import vrview
from vrpack import require
from merge_walk_clip import clip_offset


def digest(path):
    data=path.read_bytes();return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def finish(root, source, exported, imported, merged, output, parity):
    config=json.loads((source/'export_config.json').read_text())
    take=next(x for x in config['source_takes'] if x['name']=='normal_walk_r1')
    require(take['action']=='normal_walk_r1' and take['frame_start']==1 and take['frame_end']==45 and take['loop'] and config['source_fps']==60,'unsupported walk source contract')
    result=json.loads(parity.read_text())
    require(result['passed'] and result['backend']=='Rust CPU sampler','Rust native parity must pass')
    original=root/'assets/locomotion/asset.vra';old=original.read_bytes();new=(merged/'asset.vra').read_bytes()
    require(new[clip_offset(new)+4:clip_offset(new)+len(old)-clip_offset(old)]==old[clip_offset(old)+4:],'legacy clip bytes differ')
    for ext in ('vrs','vrm'):
        require((merged/f'asset.{ext}').read_bytes()==(root/f'assets/locomotion/asset.{ext}').read_bytes(),'canonical companions differ')
    pack=vrview.decode_vra(new);walk=next(c for c in pack['clips'] if c['name']=='normal_walk_r1')
    require(len(pack['clips'])==44 and walk['loop'],'runtime walk contract differs')
    require(walk['frames'][-1]['time']==__import__('vrpack').f32(44/60),'walk duration differs')
    output.mkdir(parents=True,exist_ok=False)
    for ext in ('vra','vrm','vrs'):shutil.copyfile(merged/f'asset.{ext}',output/f'asset.{ext}')
    shutil.copyfile(parity,output/'parity.json')
    shutil.copyfile(imported/'manifest.json',output/'conversion.json')
    skin=(output/'asset.vrs').read_bytes();compressed=gzip.compress(skin,mtime=0)
    (output/'asset.vrs.gz').write_bytes(compressed)
    manifest={'schema':'rust-duty-authored-walk-distribution/v1','clip_count':44,
      'clip_names':[c['name'] for c in pack['clips']], 'walk_clip':'normal_walk_r1','loop':True,
      'source':{'file':'assets/authoring/locomotion/locomotion.blend', **digest(source/'locomotion.blend'),
                'action':take['action'],'frame_start':take['frame_start'],'frame_end':take['frame_end'],
                'fps':config['source_fps'],'fbx':digest(exported/'locomotion.fbx')},
      'files':{f'asset.{ext}':digest(output/f'asset.{ext}') for ext in ('vra','vrs','vrm')},
      'preservation':{'original_vra_sha256':digest(original)['sha256'],'clip_payloads_byte_identical':43,
                      'canonical_skin_byte_identical':True,'canonical_rigid_byte_identical':True,
                      'normal_ready_retained':True,'normal_settle_byte_identical':True},
      'validation':{'backend':result['backend'],'samples':result['samples'],'passed':result['passed'],
                    'maxima':result['maxima'],'position_limit_m':result['declared_position_limit_m'],
                    'visibility_failures':result['visibility_failures'],'report':'parity.json'},
      'repository_transport':{'asset.vrs':{'file':'asset.vrs.gz','encoding':'gzip',**digest(output/'asset.vrs.gz'),
                            'decoded_bytes':len(skin),'decoded_sha256':hashlib.sha256(skin).hexdigest()}},
      'scope':'New authored walk only; legacy43 and settle preserved. Numerical runtime parity is not gameplay visual approval.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--blender',default='blender');p.add_argument('--sampler',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.root.resolve();source=root/'assets/authoring/locomotion';work=args.work.resolve()
    require(not work.exists() and not args.output.exists(),'use new work and output destinations')
    work.mkdir(parents=True);exported=work/'fbx';imported=work/'imported';merged=work/'merged';parity=work/'parity.json'
    def run(cmd):subprocess.run(list(map(str,cmd)),cwd=root,check=True)
    run([sys.executable,root/'tools/package_game.py','materialize','--root',root])
    run([args.blender,'--background','--factory-startup','--disable-autoexec',source/'locomotion.blend',
         '--python-exit-code','1','--python',source/'export_locomotion.py','--','--config',source/'export_config.json','--output-dir',exported])
    run([args.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
         '--python',root/'tools/import_fbx_viewmodel.py','--','--fbx',exported/'locomotion.fbx',
         '--fbx-sha256',digest(exported/'locomotion.fbx')['sha256'],'--source-sha256',digest(source/'locomotion.blend')['sha256'],
         '--material-source',source/'locomotion.blend','--skeleton-vra',root/'assets/locomotion/asset.vra','--output',imported,
         '--actor','hk416_weapon','--actor','hk416_magazine','--native-start','0','--native-end','44','--subdivisions','8',
         '--fps','60','--take','normal_walk_r1','--imported-frame-offset','0','--name','normal_walk_r1','--loop'])
    run([sys.executable,root/'tools/merge_walk_clip.py',root/'assets/locomotion/asset.vra',imported/'asset.vra',merged])
    run([sys.executable,root/'tools/verify_locomotion_fbx.py',merged/'asset.vra',exported/'native_oracle.npz',
         '--oracle-json',exported/'native_oracle.json','--clip','normal_walk_r1','--canonical-companions',
         '--sampler',args.sampler.resolve(),'--report',parity])
    finish(root,source,exported,imported,merged,args.output.resolve(),parity)

if __name__=='__main__':main()
