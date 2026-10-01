#!/usr/bin/env python3
"""Compare the independent Blender fixture oracle with the Rust VRA sampler.
All geometry checks use actual evaluated/skinned vertices, not pose labels.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path


def point_error(expected, actual):
    """Match all vertices one-to-one; GLB exporters may reorder vertex records."""
    if len(expected) != len(actual):
        raise AssertionError(f'vertex count changed: {len(expected)} != {len(actual)}')
    remaining = list(actual); maximum = 0.0
    for vertex in expected:
        at, distance = min(enumerate(math.dist(vertex, other) for other in remaining), key=lambda row: row[1])
        maximum = max(maximum, distance); remaining.pop(at)
    return maximum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('oracle', type=Path)
    parser.add_argument('asset', type=Path)
    parser.add_argument('--sampler', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    oracle = json.loads(args.oracle.read_text())
    assert oracle['schema'] == 'original-blender-viewmodel-oracle/v1'
    groups = {}
    for sample in oracle['samples']: groups.setdefault(sample['clip'], []).append(sample)
    assert set(groups) == {'neutral', 'left_release', 'right_release'}
    metrics = {label:{'max_bone_matrix_component_error':0.,'max_skin_position_error_m':0.,'max_rigid_position_error_m':0.,'samples':0} for label in ['sampled_frames','between_frames']}
    records = []
    for clip, samples in groups.items():
        command = [str(args.sampler.resolve()),str(args.asset.resolve()),clip,*[str(s['time']) for s in samples],'--clamp']
        run = subprocess.run(command, text=True, capture_output=True, check=True)
        actual = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
        assert len(actual)==len(samples), f'{clip}: wrong sample count'
        for gold, got in zip(samples, actual):
            assert got['clip']==clip
            gb={row['name']:row['global'] for row in gold['bones']}
            rb={row['name']:row['global'] for row in got['bones']}
            assert set(gb)==set(rb), f'bone set changed: {set(gb)^set(rb)}'
            matrix=max(abs(a-b) for name in gb for a,b in zip(gb[name],rb[name]))
            skin=point_error(gold['skin_positions'],[p for m in got['skin_meshes'] for p in m['positions']])
            rigid=point_error(gold['rigid_positions'],[p for m in got['rigid_meshes'] for p in m['positions']])
            kind='sampled_frames' if gold['frame'].is_integer() else 'between_frames'
            m=metrics[kind]; m['samples']+=1
            for key,value in [('max_bone_matrix_component_error',matrix),('max_skin_position_error_m',skin),('max_rigid_position_error_m',rigid)]: m[key]=max(m[key],value)
            records.append({'clip':clip,'frame':gold['frame'],'matrix_error':matrix,'skin_error_m':skin,'rigid_error_m':rigid})
    # These are declared fixture tolerances, not a claim of exact continuous IK.
    limits={'sampled_frames':{'max_bone_matrix_component_error':5e-5,'max_skin_position_error_m':5e-5,'max_rigid_position_error_m':5e-5},
            'between_frames':{'max_bone_matrix_component_error':.025,'max_skin_position_error_m':.005,'max_rigid_position_error_m':.0002}}
    failures=[]
    for kind,values in limits.items():
        for key,limit in values.items():
            if metrics[kind][key]>limit: failures.append(f'{kind} {key}={metrics[kind][key]} > {limit}')
    # Independently confirm fixture exercised both hand constraints and distinct clips.
    constraint_checks=[]
    for clip,side,other in [('left_release','l','r'),('right_release','r','l')]:
        samples={s['frame']:s for s in groups[clip]}
        for frame,influence in [(1.,1.),(4.,.5),(7.,0.),(10.,.5),(13.,1.)]:
            c=samples[frame]['constraints']; assert abs(c[side]['influence']-influence)<1e-7
            assert c[other]['influence']==1. and c[other]['target_distance']<1e-5
            if influence==0.: assert c[side]['target_distance']>.1
            if influence==1.: assert c[side]['target_distance']<1e-5
            constraint_checks.append({'clip':clip,'frame':frame,'independent_hand':side,'influence':influence,'other_target_error_m':c[other]['target_distance']})
    # Verify the axis at the runtime boundary by comparing every emitted point.
    axis_run=subprocess.run([str(args.sampler.resolve()),str(args.asset.resolve()),'neutral','0','--game-axis','--clamp'],text=True,capture_output=True,check=True)
    game=json.loads(axis_run.stdout.strip())
    gold=groups['neutral'][0]
    axis_error=max(point_error([[-p[0],p[1],-p[2]] for p in gold[source]], [p for m in game[target] for p in m['positions']]) for source,target in [('skin_positions','skin_meshes'),('rigid_positions','rigid_meshes')])
    if axis_error>5e-5: failures.append(f'axis vertex error {axis_error}')
    report={'schema':'blender-runtime-roundtrip-proof/v1','passed':not failures,'metrics':metrics,'declared_tolerances':limits,
            'axis_error_m':axis_error,'constraint_checks':constraint_checks,'samples':records,'failures':failures,
            'scope':'Original synthetic two-armature fixture only. Exact sample-frame agreement; finite-rate interpolation error measured separately. No gameplay/source-reference fidelity claim.'}
    args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','metrics','axis_error_m','failures']},indent=2))
    if failures: raise SystemExit(1)


if __name__=='__main__': main()
