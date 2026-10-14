#!/usr/bin/env python3
"""Measure the documented static HK416 calibration, independently of authored replay.

The caller establishes source/executable/asset/settings provenance and native
process receipts. This module checks each raw capture/witness before full-frame
contour localization. It never learns a position from the calibration target.
"""
from decimal import Decimal
import math
from pathlib import Path
import calibrated_sight_contours as contours
import run_dx12_authored as captures
import verify_capture_frame_witness as witness
from verify_capture_telemetry import read_record, validate
from verify_render_capture import verify as verify_png

ASSET_SHA256 = '082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa'
SETTINGS = b'viewmodel_x = 0\nviewmodel_y = 0\nviewmodel_z = 0\n'
SCHEMA = 'rust-duty-calibrated-static-presentation/v1'
DOCUMENTED_FRAMING = {'hfov':76, 'hip':[0.05930,-0.04831,-0.30806],
    'ads':[0,-0.03794,-0.2322], 'hip_ypr':[0.04118,-0.01252,0], 'ads_ypr':[0,0,0]}

TARGETS = {'hip': (526, 280), 'ads': (480, 270)}
FEATURES = {'hip': ('hip-front-sight-guard', 'far_opening_candidate', 29),
            'ads': ('ads-rear-aperture-center', 'near_surround_candidate', 27)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(binding, backend, pose):
    require(backend in ('OpenGl', 'Dx12') and pose in TARGETS, 'unknown static capture')
    return witness.capture_identity({**{k: binding[k] for k in ('source_commit', 'run_id', 'run_attempt')},
        'exe_sha256': binding['executable_sha256'], 'scenario': f'calibrated-static-{pose}', 'backend': backend})


def projected_feature_shapes(pose):
    """Source geometry only; calibration target coordinates are not consulted.

    Rim centers/radii are independently fitted to the approved static VRM
    mesh27 (near) and mesh29 (far), on both depth faces. Projection labels
    source/depth/scale for inspection; it does not invent measured pixels.
    """
    require(pose in TARGETS, 'unknown static pose')
    translation = (0.05930,-0.04831,-0.30806) if pose == 'hip' else (0,-0.03794,-0.2322)
    yaw,pitch = (0.04118,-0.01252) if pose == 'hip' else (0.,0.)
    focal=480/math.tan(math.radians(76)/2)
    def project(point):
        x,y,z=point
        y,z=math.cos(pitch)*y-math.sin(pitch)*z,math.sin(pitch)*y+math.cos(pitch)*z
        x,z=math.cos(yaw)*x+math.sin(yaw)*z,-math.sin(yaw)*x+math.cos(yaw)*z
        x,y,z=(x+translation[0],y+translation[1],z+translation[2])
        require(z < 0, 'source rim is behind the reference camera')
        return (480+focal*x/-z,270-focal*y/-z,-z)
    result={}
    for label,mesh,y,z,radius in (
            ('near_surround_candidate',27,.03792992,.04844119,.00623376),
            ('far_opening_candidate',29,.03792994,-.31175627,.00242995)):
        center=project((0,y,z))
        ring=[project((radius*math.cos(i*math.pi/32),y+radius*math.sin(i*math.pi/32),z)) for i in range(64)]
        result[label]={'mesh_index':mesh,'source_center':[0,y,z],'source_inner_radius_m':radius,
            'projected_center_only':list(center[:2]),'camera_depth_m':center[2],
            'projected_inner_extent_px':[max(p[a] for p in ring)-min(p[a] for p in ring) for a in (0,1)]}
    require(result['near_surround_candidate']['camera_depth_m'] < result['far_opening_candidate']['camera_depth_m'],
            'source near/far ordering changed')
    return result


def validate_capture(folder, backend, pose, expected_identity):
    require(backend in ('OpenGl', 'Dx12') and pose in TARGETS, 'unknown static capture')
    folder = Path(folder)
    image = folder / f'{pose}.png'
    expected = {image.name + suffix for suffix in ('', '.json', '.world.png', '.world.png.json', '.lighting.json')}
    require(folder.is_dir() and not folder.is_symlink(), 'capture folder must be a real directory')
    require({p.name for p in folder.iterdir()} == expected, 'missing or unexpected static capture files')
    validate(folder, expected_backend=backend)
    metadata = captures.capture_metadata(image, backend)
    require(metadata.get('capture') == 'native offscreen viewmodel', 'not the documented reference target')
    require((metadata['width'], metadata['height']) == (960, 540), 'wrong reference extent')
    require(type(metadata.get('hfov')) in (int, Decimal) and metadata['hfov'] == 76, 'calibrated HFOV changed')
    require(type(metadata.get('ads')) in (int, Decimal) and metadata['ads'] == int(pose == 'ads'), 'wrong calibrated pose')
    require('reload_phase' in metadata and metadata['reload_phase'] is None, 'reload is not a static landmark pose')
    require(metadata.get('requested') == ('dx12' if backend == 'Dx12' else 'gl'), 'wrong explicit renderer')
    if backend == 'OpenGl':
        require(metadata['adapter'].casefold().startswith('llvmpipe'), 'GL reference must be actual llvmpipe')
    light = captures.validate_lighting_record(Path(str(image) + '.lighting.json'))
    require(light['simulation_time'] == 0, 'static diagnostic did not freeze simulation time')
    witness.verify(image, metadata, 0, expected_identity)
    # The unchanged nonempty/structure check is independent of marker decoding.
    image_check = verify_png(image, (960,540), captures.BACKGROUND, 0.01, 8, None)
    measured = contours.measure(image, pose)
    require(measured['status'] == 'unique-constellation-candidate', 'landmark opening constellation is absent or ambiguous')
    require(all(row['pair_count'] == 1 for row in measured['threshold_sensitivity']),
            'landmark identity changes under threshold sensitivity probes')
    geometry=projected_feature_shapes(pose)
    # Association uses source-derived depth/scale, never target location or a
    # target-sized search box. Pixel centers still come only from full-frame
    # contours. Raster/occlusion scale slack is a detector identity check.
    for key,shape in geometry.items():
        left,top,right,bottom=measured['candidates'][key]['bounds_inclusive']
        actual=(right-left+1,bottom-top+1)
        require(all(max(2.,expected*.5-1) <= got <= expected*1.5+2
                    for got,expected in zip(actual,shape['projected_inner_extent_px'])),
                'opening scale does not match the source-identified sight assembly')
    feature, candidate, mesh = FEATURES[pose]
    point = measured['candidates'][candidate]['contour_midrange_center']
    comparison = contours.calibration_comparison(point, TARGETS[pose])
    return {'backend': backend, 'pose': pose, 'feature': feature, 'asset_mesh_index': mesh,
            'image_sha256': captures.sha256(image), 'measured_center': point,
            'calibrated_center': list(TARGETS[pose]), 'tolerance_px': 4,
            'calibration': comparison, 'within_tolerance': comparison['within_original_inclusive_4px'],
            'witness_identity': expected_identity, 'image_check': image_check,
            'contour_evidence': measured, 'source_geometry_association':geometry,
            'detector_applicability':'native-review-pending',
            'scope': 'Static calibrated weapon contour pixels only; authored replay/contact and human review remain separate.'}


def paired_results(measurements):
    expected = {(backend,pose) for backend in ('OpenGl','Dx12') for pose in TARGETS}
    keyed = {(m['backend'],m['pose']): m for m in measurements}
    require(len(measurements) == 4 and set(keyed) == expected, 'all four distinct calibrated captures are required')
    deltas = [{'pose': pose, 'feature': FEATURES[pose][0],
               'dx12_minus_gl_px': contours.position_delta(keyed['Dx12',pose]['measured_center'],keyed['OpenGl',pose]['measured_center']),
               'acceptance_predicate': False} for pose in TARGETS]
    return {'passed': all(m['within_tolerance'] is True for m in measurements),
            'measurements': measurements, 'paired_backend_deltas': deltas,
            'human_visual_gate': 'open', 'hardware_playtest_gate': 'open',
            'authored_replay_acceptance': 'separate-required-gate'}


def verify_evidence(evidence, expected_binding):
    """Recheck transported same-attempt evidence; expected binding comes from build inputs."""
    import json
    import dx12_authored_shards as shards
    import aggregate_dx12_authored as aggregate
    import run_calibrated_presentation as runner
    from verify_capture_telemetry import _compare
    evidence=Path(evidence)
    require(evidence.is_dir() and not evidence.is_symlink(),'fixture artifact must be a real directory')
    summary=read_record(evidence/'summary.json')
    require(summary.get('schema')==SCHEMA and summary.get('passed') is True and summary.get('status')=='passed',
            'static fixture did not pass')
    binding=summary.get('binding')
    require(isinstance(binding,dict),'static fixture binding missing')
    for key in ('source_commit','run_id','run_attempt','executable_sha256'):
        require(binding.get(key)==expected_binding.get(key) and isinstance(binding.get(key),str),f'static fixture differs in {key}')
    require(binding.get('platform')=='win32' and binding.get('asset_sha256')==ASSET_SHA256,'wrong static asset/platform')
    shards.verify_files(evidence,summary.get('files'))
    require(captures.sha256(evidence/'gl-runtime/vector-range.exe')==binding['executable_sha256'],'staged executable differs from build inputs')
    require((evidence/'calibration-settings.cfg').read_bytes()==SETTINGS,'static settings changed')
    require(captures.sha256(evidence/'calibration-settings.cfg')==binding.get('settings_sha256'),'settings hash differs')
    _compare(read_record(evidence/'input-manifest.json'),binding,'fixture input manifest')
    names=['validated-static-inputs','opengl-hip','opengl-ads','dx12-hip','dx12-ads',
           'original-calibration-and-separate-paired-deltas','inputs-unchanged']
    checks=summary.get('checks')
    require(isinstance(checks,list) and [row.get('name') for row in checks]==names
            and all(row.get('passed') is True for row in checks),'missing or failed static fixture checks')
    measured=[]
    for backend in ('OpenGl','Dx12'):
        for pose in ('hip','ads'):
            name=backend.lower()+'-'+pose;logs=evidence/'logs'/name
            argv=aggregate.process_receipt(logs,900,1)
            def argument(prefix):
                matches=[arg[len(prefix):] for arg in argv if arg.startswith(prefix)]
                require(len(matches)==1,f'missing or duplicate {prefix}')
                return matches[0]
            expected=identity(binding,backend,pose)
            # Preserve original Windows path strings after artifact transport.
            from pathlib import PureWindowsPath
            path_type=PureWindowsPath if '\\' in argv[0] else Path
            rebuilt=runner.command(path_type(argv[0]),path_type(argument('--weapon-asset=')),
                path_type(argument('--settings=')),path_type(argument('--output=')).parent,backend,pose,expected)
            require(argv==rebuilt,'static invocation changed flags, pose or witness')
            text='\n'.join((logs/file).read_text(encoding='utf-8',errors='replace') for file in ('stdout.log','stderr.log'))
            require('Loaded VRMESH01 weapon: 30 mesh parts' in text and 'could not load' not in text.casefold(),'static model did not load')
            if backend=='Dx12':captures.renderer_logs(logs)
            else:runner.native.legacy_renderer_logs(logs)
            measured.append(validate_capture(evidence/'captures'/name,backend,pose,expected))
    recorded=summary.get('measurements')
    require(isinstance(recorded,list) and len(recorded)==4,'missing recorded measurements')
    keys=('backend','pose','feature','asset_mesh_index','image_sha256','measured_center','calibrated_center','tolerance_px','within_tolerance','witness_identity')
    for before,after in zip(recorded,measured):
        _compare({k:before.get(k) for k in keys},json.loads(json.dumps({k:after[k] for k in keys}),parse_float=Decimal),'recorded/raw measured landmarks')
    result=paired_results(measured)
    require(result['passed'],'revalidated static calibration is outside tolerance')
    shards.verify_files(evidence,summary['files'])
    return {'schema':SCHEMA,'passed':True,'binding':binding,'revalidated_raw_captures':4,
            'comparison':result,'scope':'Static calibration only; full authored aggregate remains required.'}


def main():
    import argparse
    import json
    import sys
    import dx12_authored_shards as shards
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--input-manifest',type=Path,required=True)
    args=parser.parse_args()
    try:
        manifest=read_record(args.input_manifest);binding=manifest['binding'];shards.validate_binding(binding)
        result=verify_evidence(args.evidence,binding)
    except (OSError,ValueError,KeyError) as error:
        print(f'Calibrated fixture verification failed: {error}',file=sys.stderr);return 1
    print(json.dumps(result,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
