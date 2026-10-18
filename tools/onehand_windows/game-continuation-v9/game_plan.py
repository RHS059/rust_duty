"""Exact same-job current-game generation/build commands, never historical assets."""
from pathlib import Path
from continuation_core import ACTION,FEATURES,TARGET,need

JUMP_REF='e9317f90ea171976306e2f17c111325d948ea357'
JUMP_PATH='assets/authoring/jump/halcyon_jump.blend'
KINDS=('reload','walk','ads','directional','jump')

def generator_plan(root,work,python,blender,sampler):
    root,work=Path(root),Path(work)
    def py(tool,*args):return [str(python),'-B',str(root/'tools'/tool),*map(str,args)]
    jobs=[{'label':'game-base-materialize','argv':py('package_game.py','materialize','--root',root)}]
    jobs += [
        {'label':'game-base-reload-export','argv':py('build_blender_assets.py','--root',root,'--blender',blender,'--output',work/'reload')},
        {'label':'game-base-reload-parity','argv':py('build_blender_assets.py','--root',root,'--verify-sampler',sampler,'--output',work/'reload')},
        {'label':'game-base-reload-check','argv':py('check_generated_assets.py','--root',root,'--kind','reload','--directory',work/'reload/reload'),'stage':{'kind':'reload','source':str(work/'reload/reload'),'destination':str(root/'assets/reload')}}]
    for kind in KINDS[1:]:
        args=['--root',root,'--blender',blender,'--sampler',sampler,'--work',work/kind/'work','--output',work/kind/'runtime']
        if kind=='jump':args+=['--source-dir',root/'.jump-source/assets/authoring/jump']
        jobs.append({'label':'game-base-'+kind+'-export','argv':py('build_'+kind+'_assets.py',*args)})
        jobs.append({'label':'game-base-'+kind+'-check','argv':py('check_generated_assets.py','--root',root,'--kind',kind,'--directory',work/kind/'runtime'),'stage':{'kind':kind,'source':str(work/kind/'runtime'),'destination':str(root/'assets'/kind)}})
    jobs.append({'label':'game-base-final-materialize','argv':py('package_game.py','materialize','--root',root,'--include-walk','--include-ads','--include-directional','--include-jump','--require-generated')})
    return jobs

def cargo_command(cargo,target,kind):
    need(kind in ('sampler','game'),'unknown build target')
    command=[str(cargo),'build','--locked','--offline','--release','--message-format=json','--target',TARGET,'--target-dir',str(target),'--no-default-features']
    if kind=='sampler':command+=['--example','sample_viewmodel_clip']
    else:command+=['--features',','.join(FEATURES),'--bin','vector-range']
    return command

def capture_command(executable,manifest,settings,output,identity,hz):
    need(hz in (30,60),'capture rate must be 30 or 60')
    return [str(executable),'--renderer=dx12','--force-fallback-adapter','--level=range','--hold-controls','--no-update',
        '--animation-manifest='+str(manifest),'--settings='+str(settings),
        '--onehand-observer='+str(output),'--onehand-witness='+identity,
        '--onehand-deterministic','--capture-sequence=gameplay-high-onto','--capture-hz='+str(hz),'--capture-native-window']
