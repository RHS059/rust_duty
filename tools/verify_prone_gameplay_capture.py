#!/usr/bin/env python3
"""Read-only verification of frozen r15 native-window gameplay capture evidence.

No game, graphics, native input, asset conversion or network access is performed.
The only writes are an explicitly selected JSON report. Original PNGs and all
inputs remain untouched. Witness helpers can be supplied with --witness-tools;
their exact source-free bytes are checked before loading. Deterministic sampling
rates are not real-time FPS claims, and pixel/telemetry checks are not art approval.
"""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

EXE_SHA = 'afae906f1984462cc3153216bb3269e159871943cf8767510aa4d24e9907938b'
SOURCE_COMMIT = 'b9d07be18aa0b4fd383516ca0786e7f5f792d0d8'
DRIVER_SHA = '92fef40c81c8387c87ac0fdcc57270ef3a122d56f246aac83d9a5d7b16d6cbbc'
VRA_SHA = '53e360817acd58e4f826ae0be7c316a55f699a5c46d211dbbaf6256e779bec86'
RECEIPT_SHA = '21b40755782e8731d25525af432d3db54820b0100caa0e0debb2f0f3a4c22da1'
DEFAULT_MANIFEST_SHA = 'a13e146097d8e0044c3dbdab704e9fec6dd19a18ecd16fdc94f6df908ee4cb28'
HELPER_SHAS = {
    'verify_capture_frame_witness.py': '00011d1904499e1c2c0ea93b4cb74e389d1bf7b78cb0459567b3ae7f65f0f678',
    'verify_render_capture.py': '6bea6d0c9ebabe48bf50c8e45a370652d93bf926bbba3e8326bc754cbff395af',
}
BINDING_KEYS = ('action_fingerprints', 'asset_vra_sha256', 'camera_sample_hz',
                'camera_sidecar_sha256', 'candidate_frame_offset', 'candidate_sha256',
                'clip_name', 'common_motion_removal', 'native_crop', 'source_camera_action',
                'source_fbx_sha256', 'source_rig_action')
SEGMENTS = [(0., 'ready'), (.15, 'crouch'), (.55, 'prone_entry_hold'),
            (1.85, 'stance_return'), (2.3, 'second_crouch'), (2.7, 'second_prone_entry'),
            (3.2, 'ads_interrupt_return'), (3.6, 'live_ads_walk'), (3.8, 'live_walk'),
            (4.1, 'stance_exit')]
TOLERANCE = 2e-6
ENTRY_DURATION = 68 / 60


class VerificationError(ValueError):
    """Evidence did not establish the stated contract."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'not a regular file: {path}')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    def reject(value):
        raise VerificationError(f'non-finite JSON value: {value}')
    return json.loads(Path(path).read_text(), parse_constant=reject)


def near(a, b, tolerance=TOLERANCE):
    return type(a) in (int, float) and math.isfinite(a) and abs(a - b) < tolerance


def finite(value):
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, list):
        return all(finite(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def vector(value, length):
    return isinstance(value, list) and len(value) == length and all(
        type(v) in (int, float) and math.isfinite(v) for v in value)


def close_vector(a, b, tolerance=TOLERANCE):
    return len(a) == len(b) and all(near(x, y, tolerance) for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def rotate(q, v):
    uv = cross(q[:3], v)
    uuv = cross(q[:3], uv)
    return [v[i] + 2 * (q[3] * uv[i] + uuv[i]) for i in range(3)]


def identity_slerp(q, weight):
    q = [x if q[3] >= 0 else -x for x in q]
    angle = math.acos(min(1., max(-1., q[3])))
    if angle < 1e-6:
        result = [x * (1-weight) for x in q[:3]] + [q[3]*(1-weight)+weight]
    else:
        a = math.sin((1-weight)*angle)/math.sin(angle)
        b = math.sin(weight*angle)/math.sin(angle)
        result = [x*a for x in q[:3]] + [q[3]*a+b]
    norm = math.sqrt(dot(result, result))
    return [x/norm for x in result]


def expected_binding(receipt):
    return {**{k: receipt[k] for k in BINDING_KEYS},
            'receipt_schema': receipt['schema'],
            'sidecar_schema': 'prone-entry-r15-camera-motion/v1',
            'schema': 'rust-duty-prone-loaded-binding/v1'}


def validate_input_hashes(root, pins):
    require(isinstance(pins, dict) and pins, 'missing input pins')
    for name, digest in pins.items():
        rel = Path(name)
        require(not rel.is_absolute() and '..' not in rel.parts, 'unsafe input pin path')
        require(sha(root / rel) == digest, f'capture input stale: {name}')
    return hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()


def expected_command(root, folder, hz, identity):
    return [str(folder/'frozen-vector-range'), '--renderer=gl', '--level=range', '--capture',
            '--capture-native-window', '--capture-sequence=gameplay-prone', f'--capture-hz={hz}',
            f'--animation-manifest={root/"private-runtime-pack-v1/animations.cfg"}',
            f'--capture-frame-witness={identity}', f'--output={folder/str(hz)}']


def validate_frame(v, index, hz, binding):
    tag = f'{hz} Hz frame {index}'
    require(v['schema'] == 'rust-duty-prone-gameplay-capture/v1' and finite(v), f'{tag}: schema/non-finite')
    t = v['simulation_time']
    require(near(t, index/hz) and v['sampling_hz'] == hz, f'{tag}: capture clock mismatch')
    require(v['binding'] == binding, f'{tag}: loaded binding mismatch')
    require(v['input_only_replay'] is True and v['renderer_failed'] is False, f'{tag}: replay/render failure')
    expected_segment = next(name for start, name in reversed(SEGMENTS) if t >= start)
    require(v['segment'] == expected_segment, f'{tag}: replay segment mismatch')
    for key in ('camera_forward', 'camera_up', 'camera_eye', 'position', 'velocity', 'gameplay_direction'):
        require(vector(v[key], 3), f'{tag}: invalid {key}')
    require(near(dot(v['camera_forward'],v['camera_forward']), 1., 3e-5)
            and near(dot(v['camera_up'],v['camera_up']),1.,3e-5)
            and near(dot(v['camera_forward'],v['camera_up']),0.,3e-5), f'{tag}: camera basis invalid')
    require(close_vector(v['camera_eye'], [v['position'][0], v['position'][1]+v['eye_height'], v['position'][2]]),
            f'{tag}: camera eye/physics mismatch')
    require(v['grounded'] is True and near(v['position'][1], 0.) and near(v['velocity'][1], 0.),
            f'{tag}: unexpected physics')
    require((v['ammo'],v['reserve'],v['shots'],v['reload_left'],v['reload_ready_at']) == (30,90,0,0,0),
            f'{tag}: ammo/reload mutated')
    require(all(0 <= v[k] <= 1 for k in ('procedural_weight','visual_ads','simulation_ads')), f'{tag}: invalid weight')
    active_start = .55 if .55+TOLERANCE < t <= 1.85+TOLERANCE else (
        2.7 if 2.7+TOLERANCE < t <= 3.2+TOLERANCE else None)
    return_start = 1.85 if 1.85+TOLERANCE < t < 2.05-TOLERANCE else (
        3.2 if 3.2+TOLERANCE < t < 3.4-TOLERANCE else None)
    sample, outgoing, q = v['source_clock'], v['return'], v['camera_orientation_xyzw']
    if active_start is not None:
        require(isinstance(sample, dict) and outgoing is None and q is not None
                and v['route'] == 'prone.entry_hold' and v['prone'] and v['procedural_weight'] == 0,
                f'{tag}: source route mismatch')
        require(near(sample['frame'], 1 + 60*sample['seconds'], 1e-7), f'{tag}: seconds/frame mismatch')
        require(near(sample['seconds'], min(t-(active_start+1/120), ENTRY_DURATION)),
                f'{tag}: source clock stretched or stale')
        require(1 <= sample['frame'] <= 69 and 0 <= sample['seconds'] <= ENTRY_DURATION,
                f'{tag}: source clock out of range')
        require(not v['ads_requested'] and v['simulation_ads'] == 0 and v['visual_ads'] == 0,
                f'{tag}: active source ADS mismatch')
    elif return_start is not None:
        require(sample is None and isinstance(outgoing, dict) and q is not None
                and v['route'] == 'prone.return', f'{tag}: outgoing route mismatch')
        require(near(outgoing['began'], return_start) and outgoing['duration'] == .2,
                f'{tag}: outgoing clock mismatch')
        x = max(0., min(1., (t-outgoing['began'])/outgoing['duration']))
        w = x*x*(3-2*x)
        require(near(outgoing['weight'],w,1e-7) and near(v['procedural_weight'],w,1e-7),
                f'{tag}: outgoing smoothstep/procedural weight mismatch')
        expected_frozen = 69 if return_start == 1.85 else 30.5
        require(near(outgoing['frozen_source_frame'],expected_frozen,1e-5), f'{tag}: frozen source mismatch')
    else:
        require(sample is None and outgoing is None and q is None and not v['route'].startswith('prone.')
                and v['procedural_weight'] == 1., f'{tag}: stale source/return route or automatic restart')
    if q is not None:
        require(vector(q,4) and near(dot(q,q),1.,3e-5), f'{tag}: camera quaternion invalid')
        f = v['gameplay_direction']; r = cross(f,[0.,1.,0.]); u = cross(r,f)
        def world(local):
            return [r[i]*local[0]+u[i]*local[1]-f[i]*local[2] for i in range(3)]
        require(close_vector(v['camera_forward'],world(rotate(q,[0.,0.,-1.])),3e-5)
                and close_vector(v['camera_up'],world(rotate(q,[0.,1.,0.])),3e-5), f'{tag}: quaternion/basis mismatch')
    else:
        require(close_vector(v['camera_forward'],v['gameplay_direction'],3e-5)
                and close_vector(v['camera_up'],[0.,1.,0.],3e-5), f'{tag}: camera not restored')


def validate_sequence(frames, hz):
    require(len(frames) == {60:283,30:142}[hz], 'capture count does not match actual 4.5 s + 0.2 s boundary')
    require(near(frames[-1]['simulation_time'],4.7), 'capture terminal boundary differs')
    aim=frames[0]['gameplay_direction']
    require(all(close_vector(v['gameplay_direction'],aim,1e-7) for v in frames), 'gameplay aim changed')
    require(max(math.sqrt(sum((a-b)**2 for a,b in zip(v['camera_forward'],aim)))
                + abs(v['camera_up'][0]) for v in frames) > 1e-4, 'cosmetic camera never rotated')
    native=[v for v in frames if v['source_clock'] is not None]
    first=[v for v in native if v['simulation_time']<2.]
    second=[v for v in native if v['simulation_time']>2.]
    require(first and second and first[-1]['source_clock']['frame']==69
            and sum(v['source_clock']['frame']==69 for v in first)>=3,
            'first entry did not hold source endpoint 69')
    require(max(v['source_clock']['frame'] for v in second)<69, 'second entry did not cancel before endpoint')
    require(any(v['visual_ads']>.99 and v['simulation_ads']>.99 for v in frames if 3.5<v['simulation_time']<3.8),
            'live ADS did not resume')
    require(frames[-1]['position'][2] < frames[0]['position'][2]-.1, 'live movement did not resume')
    require(all(v['source_clock'] is None and v['return'] is None for v in frames if 3.4+TOLERANCE<v['simulation_time']<4.1),
            'holding prone after ADS cancel restarted source')
    for begin,group in ((1.85,first),(3.2,second)):
        returns=[v for v in frames if v['return'] is not None and near(v['return']['began'],begin)]
        require(returns, 'missing outgoing blend')
        q=group[-1]['camera_orientation_xyzw']
        require(all(close_vector(v['camera_orientation_xyzw'],identity_slerp(q,v['return']['weight']),3e-5)
                    for v in returns), 'outgoing camera did not share smoothstep clock')
        require(all(a['return']['weight']<b['return']['weight'] for a,b in zip(returns,returns[1:])), 'return weight not monotonic')
    return {'frames':len(frames),'native_frames':len(native),'first_native_source_frame':first[0]['source_clock']['frame'],
            'first_entry_endpoint_hold_frames':sum(v['source_clock']['frame']==69 for v in first),
            'second_entry_maximum_source_frame':max(v['source_clock']['frame'] for v in second),
            'return_frames':sum(v['return'] is not None for v in frames),
            'eye_height_range':[min(v['eye_height'] for v in frames),max(v['eye_height'] for v in frames)],
            'maximum_camera_rotation_degrees':max(2*math.degrees(math.acos(min(1.,abs(v['camera_orientation_xyzw'][3]))))
                                                for v in frames if v['camera_orientation_xyzw'] is not None),
            'constant_gameplay_aim':True,'live_ads_and_walk_resumed':True,'shared_return_clock_verified':True}


def compare_rates(fast, slow):
    require(len(fast)==283 and len(slow)==142, 'rate comparison incomplete')
    for i,v in enumerate(slow):
        other=fast[i*2]
        require({k:x for k,x in v.items() if k!='sampling_hz'} ==
                {k:x for k,x in other.items() if k!='sampling_hz'}, f'30/60 committed state differs at {i}/30 s')
    return {'shared_timestamps':len(slow),'committed_state_exactly_equal':True,
            'sampling_hz_is_only_excluded_field':True}


def load_helpers(folder):
    for name,digest in HELPER_SHAS.items():
        require(sha(folder/name)==digest, f'unverified witness helper bytes: {name}')
    sys.path.insert(0,str(folder))
    for name in ('verify_render_capture','verify_capture_frame_witness'):
        if name in sys.modules:
            require(Path(sys.modules[name].__file__).resolve()==(folder/(name+'.py')).resolve(), 'helper import collision')
    return importlib.import_module('verify_capture_frame_witness'),importlib.import_module('verify_render_capture')


def verify(root, folder, witness_tools, selected_rates=None):
    root,folder,witness_tools=map(lambda p:Path(p).resolve(),(root,folder,witness_tools))
    run_path=folder/'run.json';run=read(run_path)
    require(run['schema']=='rust-duty-prone-native-capture-run/v1'
            and run['source_contract_commit']==SOURCE_COMMIT and run['backend_requested']=='gl'
            and run['software_requested']=='llvmpipe' and run['native_platform']=='Linux'
            and run['windows_dx12_verified'] is False, 'run source/platform mismatch')
    if selected_rates is None:
        require(run.get('capture_processes_completed') is True and run.get('inputs_unchanged') is True, 'capture not terminal')
        require([v['hz'] for v in run['runs']]==[60,30], 'wrong pass ordering')
    rates=selected_rates or [60,30]
    require(set(rates)<= {60,30} and len(rates)==len(set(rates)), 'invalid requested rates')
    pins=run['inputs_sha256'];identity=validate_input_hashes(root,pins)
    require(identity==run['frame_witness'], 'run witness differs from verified input identity')
    exe=folder/'frozen-vector-range'
    require(pins.get(str(exe.relative_to(root)))==EXE_SHA and sha(exe)==EXE_SHA, 'frozen executable mismatch')
    require(sha(root/'native-gameplay/run_capture.py')==DRIVER_SHA, 'capture driver changed')
    pack=root/'private-runtime-pack-v1';receipt_path=pack/'prone_entry/asset.prone-pair.json'
    require(sha(receipt_path)==RECEIPT_SHA, 'actual pair receipt changed')
    receipt=read(receipt_path);binding=expected_binding(receipt)
    require(receipt['asset_vra_sha256']==VRA_SHA and sha(pack/'prone_entry/asset.vra')==VRA_SHA, 'actual VRA changed')
    require(sha(pack/'prone_entry/asset.prone-camera.json')==receipt['camera_sidecar_sha256'], 'actual camera changed')
    private_pins=read(root/'private-runtime-pack-v1-inputs.json')
    require({str(p.relative_to(pack)):sha(p) for p in pack.rglob('*') if p.is_file()}==private_pins, 'private pack inventory changed')
    must_pin=[exe]+[p for p in pack.rglob('*') if p.is_file()]+[p for p in (root/'source/src').rglob('*') if p.is_file()]
    must_pin += [root/'source/Cargo.toml', root/'source/Cargo.lock']
    require(set(pins)=={str(p.relative_to(root)) for p in must_pin}, 'input pin inventory incomplete/unexpected')
    for name,digest in read(root/'rust-checkpoint-verification.json')['source_files_sha256'].items():
        require(sha(root/'source'/name)==digest, f'tested source changed: {name}')
    default=root/'source/assets/animations.cfg'
    require(sha(default)==DEFAULT_MANIFEST_SHA and not any(line.startswith('prone.') for line in default.read_text().splitlines()),
            'default manifest changed or activated prone')
    witness,render=load_helpers(witness_tools)
    report={'schema':'rust-duty-r15-gameplay-capture-verification/v1','passed':False,
            'scope':'Selected terminal pass' if selected_rates else 'Both terminal capture passes',
            'source_contract_commit':SOURCE_COMMIT,'frozen_executable_sha256':EXE_SHA,
            'capture_driver_sha256':DRIVER_SHA,'capture_run_sha256':sha(run_path),'capture_identity':identity,
            'verifier_sha256':sha(__file__),'verified_input_count':len(pins),'helper_sha256':HELPER_SHAS,
            'receipt_sha256':RECEIPT_SHA,'asset_vra_sha256':VRA_SHA,'candidate_sha256':receipt['candidate_sha256'],
            'source_fbx_sha256':receipt['source_fbx_sha256'],'default_manifest_sha256':sha(default),
            'default_runtime_activation':False,'backend':'Linux OpenGl llvmpipe','capture':'native window',
            'windows_dx12_verified':False,'rates':[], 'capture_files_sha256':{},
            'limits':['Deterministic 30/60 Hz sampling is not sustained real-time rendering performance.',
                      'Delivered capture throughput includes PNG I/O and startup; it is not display frame rate.',
                      'These sidecars do not establish sustained display FPS; inspect actual HUD pixels and separate performance telemetry.',
                      'Rendered witnesses bind frames and verified invocation, not artistic or anatomical approval.',
                      'Telemetry does not independently prove every rendered rig joint or root transform; CPU parity is separate.']}
    records={}
    for hz in rates:
        entries=[v for v in run['runs'] if v['hz']==hz]
        require(len(entries)==1, f'missing/duplicate {hz} Hz invocation')
        entry=entries[0]
        require(entry.get('exit_code')==0 and near(entry.get('seconds'),entry.get('seconds',-1)) and entry['seconds']>0,
                f'{hz} Hz pass not successfully terminal')
        require(entry['command']==expected_command(root,folder,hz,identity), 'capture invocation differs')
        pngs=sorted((folder/str(hz)).glob('*.png'))
        require(len(pngs)=={60:283,30:142}[hz] and entry['pngs']==len(pngs), f'{hz} Hz count differs')
        frames=[];coverage=[]
        for i,png in enumerate(pngs):
            require(png.name==f'{i:04d}.png', 'capture PNG order/gap differs')
            primary=read(str(png)+'.json');witness.verify(png,primary,i,identity)
            require(primary['capture']=='native window' and primary['backend']=='OpenGl' and primary['requested']=='gl'
                    and 'llvmpipe' in primary['adapter'] and (primary['width'],primary['height'])==(1440,900), 'wrong renderer metadata')
            coverage.append(render.verify(png,(1440,900),(0,0,0,255),.01,8,None)['foreground_coverage'])
            v=read(str(png)+'.prone.json');validate_frame(v,i,hz,binding);frames.append(v)
            gameplay=read(str(png)+'.gameplay.json');timing=read(str(png)+'.time.json')
            require(near(gameplay['simulation_time'],v['simulation_time']) and gameplay['segment']==v['segment']
                    and gameplay['shots']==v['shots'] and gameplay['grounded']==v['grounded']
                    and near(gameplay['eye_height'],v['eye_height']) and close_vector(gameplay['position'],v['position']), 'gameplay sidecar mismatch')
            require(near(timing['elapsed_seconds'],i/hz) and timing['sampling_hz']==hz
                    and timing['visual_duration_seconds']==4.5 and near(timing['normalized_phase'],min(1.,i/hz/4.5)), 'timing sidecar mismatch')
            for p in [png]+[Path(str(png)+suffix) for suffix in ('.json','.prone.json','.gameplay.json','.time.json')]:
                report['capture_files_sha256'][str(p.relative_to(folder))]=sha(p)
        summary=validate_sequence(frames,hz);records[hz]=frames
        report['rates'].append({'hz':hz,**summary,'rendered_witnesses_verified':len(pngs),
                                'png_structure_verified':len(pngs),'minimum_foreground_coverage':min(coverage),
                                'wall_seconds':entry['seconds'],'delivered_capture_frames_per_wall_second':len(pngs)/entry['seconds']})
    if set(records)=={60,30}:
        report['rate_comparison']=compare_rates(records[60],records[30])
    require(validate_input_hashes(root,pins)==identity, 'inputs changed during verification')
    report['passed']=True
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--capture',type=Path,required=True)
    p.add_argument('--witness-tools',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--hz',type=int,choices=(60,30),action='append',help='Verify only selected already-terminal pass(es).')
    p.add_argument('--report',type=Path,help='Separate JSON output. Never an existing capture/input path.')
    args=p.parse_args(argv)
    try:
        report=verify(args.root,args.capture,args.witness_tools,args.hz)
        if args.report:
            require(not args.report.exists(), 'refusing to overwrite existing report/input')
            args.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        summary={k:v for k,v in report.items() if k!='capture_files_sha256'}
        print(json.dumps(summary,indent=2,allow_nan=False))
        return 0
    except (VerificationError,KeyError,TypeError,ValueError,OSError) as error:
        print(f'prone gameplay capture verification failed: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
