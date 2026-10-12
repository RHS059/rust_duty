#!/usr/bin/env python3
"""Bounded pre-facade/current frozen GL comparison; never general game equivalence.

The caller retrieves the one pinned historical artifact. This tool has no network
or build step and executes no archived script. It extracts only its checked game
EXE and build identity, then uses the same pinned Mesa files for both games.
Raw pixel/JSON differences remain visible; no color tolerance is introduced.
Existing authored, calibrated-witness and human gates are unchanged.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

from PIL import Image
import dx12_authored_shards as shards
import build_identity
import run_dx12_authored as authored
import run_dx12_authored_shard as native
from aggregate_dx12_authored import process_receipt
from inventory_windows_preview import normalize_zip_member, _json
from exclusive_output import write_bytes_exclusive
from run_windows_gl_reference_probe import validate_runtime
from run_windows_same_platform_return import regular, require, process_record, runtime_environment, stage_runtime
from verify_capture_telemetry import read_record, _compare
from verify_render_capture import verify as verify_png
import verify_calibrated_presentation as calibrated
import vrpack

REFERENCE = {
    'repository': 'RHS059/rust_duty',
    'source_commit': 'e7a36bcaa26e0babe4da79b3a54b3785e56bf943',
    'run_id': 37264388504, 'run_attempt': 1, 'run_number': 239,
    'artifact_id': 11326905753, 'zip_bytes': 106515067,
    'zip_sha256': '230adef228c214b3d1143e008521aa2f57aba16a45cc8d3f407a6f010d961368',
}
REFERENCE_IDENTITY = {
    'repository': REFERENCE['repository'], 'version': '0.1.11', 'sequence': 11,
    'build_number': '37264388504.1', 'display_version': '0.1.11+build.37264388504.1',
    'schema': 'rust-duty-build-identity/v1', 'target': 'x86_64-pc-windows-msvc',
    'source': {'commit': REFERENCE['source_commit'], 'branch': 'main',
               'workflow': '.github/workflows/build.yml', 'run_id': REFERENCE['run_id'],
               'run_number': REFERENCE['run_number'], 'run_attempt': REFERENCE['run_attempt'],
               'run_url': 'https://github.com/RHS059/rust_duty/actions/runs/37264388504'},
}
SCHEMA = 'rust-duty-legacy-facade-static-equivalence/v1'
COMMON_FIELDS = frozenset(('capture', 'width', 'height', 'hfov', 'ads', 'reload_phase'))
EXTENT = (960, 540)
MAX_EXE = 512 * 1024 * 1024
MAX_PNG = 16 * 1024 * 1024


def reference_executable(zip_path, destination):
    """Validate the fixed artifact and extract exactly two trusted root members."""
    zip_path, destination = regular(zip_path), Path(destination)
    require(not destination.exists() and not destination.is_symlink(), 'reference destination must be fresh')
    require(zip_path.stat().st_size == REFERENCE['zip_bytes'], 'historical ZIP size differs')
    require(authored.sha256(zip_path) == REFERENCE['zip_sha256'], 'historical ZIP digest differs')
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= 20000 and sum(i.file_size for i in infos) <= 4 * 1024**3,
                'historical ZIP inventory exceeds bounds')
        members, folded = {}, set()
        for info in infos:
            name = normalize_zip_member(info.orig_filename)
            require(name.casefold() not in folded, 'duplicate/case-colliding ZIP member')
            folded.add(name.casefold())
            mode = stat.S_IFMT(info.external_attr >> 16)
            require(mode in (0, stat.S_IFREG, stat.S_IFDIR) and not (info.external_attr & 0x400),
                    'ZIP links, special files and reparse entries are forbidden')
            require(not (info.flag_bits & 1), 'encrypted ZIP members are forbidden')
            require(mode != stat.S_IFDIR or info.is_dir(), 'ZIP directory attributes conflict')
            members[name] = info
        files = {n.casefold() for n,i in members.items() if not i.is_dir()}
        for name in members:
            require(not any('/'.join(name.split('/')[:i]).casefold() in files
                            for i in range(1, len(name.split('/')))), 'ZIP file/directory collision')
        for name in ('vector-range.exe', 'BUILD_IDENTITY.json'):
            require(name in members and not members[name].is_dir(), f'missing root historical member: {name}')
        exe_info, identity_info = members['vector-range.exe'], members['BUILD_IDENTITY.json']
        require(0 < exe_info.file_size <= MAX_EXE and 0 < identity_info.file_size <= 16384,
                'selected historical member exceeds bounds')
        identity_bytes = archive.read(identity_info)
        identity = _json(identity_bytes, 'historical BUILD_IDENTITY.json')
        record = identity.get('executable')
        require(isinstance(record, dict), 'historical executable identity missing')
        _compare({k:v for k,v in identity.items() if k != 'executable'}, REFERENCE_IDENTITY,
                 'historical build source/run identity')
        require(set(record) == {'name', 'size', 'sha256'} and record.get('name') == 'vector-range.exe'
                and type(record.get('size')) is int and record['size'] == exe_info.file_size,
                'historical executable record differs')
        with archive.open(exe_info) as source:
            executable_bytes = source.read(MAX_EXE+1)
            require(not source.read(1), 'historical EXE expands beyond bound')
        require(executable_bytes.startswith(b'MZ'), 'historical game is not a Windows EXE')
        require(len(executable_bytes) == record['size'] and len(executable_bytes) <= MAX_EXE
                and hashlib.sha256(executable_bytes).hexdigest() == record['sha256'],
                'historical executable digest/size differs from build identity')
        destination.mkdir(parents=True, exist_ok=False)
        write_bytes_exclusive(destination/'vector-range.exe',executable_bytes)
        write_bytes_exclusive(destination/'BUILD_IDENTITY.json',identity_bytes)
    require(authored.sha256(zip_path) == REFERENCE['zip_sha256'], 'historical ZIP changed while reading')
    return {'reference': dict(REFERENCE), 'identity': identity,
            'selected_member_crcs_checked': True, 'all_member_crcs_checked': False,
            'extracted_members': ['vector-range.exe', 'BUILD_IDENTITY.json']}


def command(executable, asset, settings, output, role, pose):
    require(role in ('reference', 'current') and pose in ('hip', 'ads'), 'unknown comparison role/pose')
    argv = [str(executable)]
    if role == 'current':argv.append('--renderer=gl')
    argv += ['--no-update', '--reference-viewport', '--profile=kestrel',
             f'--weapon-asset={asset}', f'--settings={settings}', '--capture', '--capture-lighting',
             f'--output={output}']
    if pose == 'ads':argv.append('--capture-ads')
    return argv


def embedded_identity(executable, cwd, logs, expected):
    """Bind actual game CLI build identity before graphics startup; no shell scripts."""
    receipts = {}
    for flag,key in (('--build-version','version'),('--build-number','build_number'),('--build-label','display_version')):
        argv = [str(executable),flag,'--no-update'];folder = Path(logs)/key
        authored.execute(argv,cwd,folder,30)
        receipt = process_record(folder,argv,cwd)
        require(process_receipt(folder,30,0) == argv, 'build identity invocation differs')
        reported = regular(folder/'stdout.log').read_text(encoding='utf-8').strip()
        require(reported == expected[key], f'embedded {key} differs from source-bound build identity')
        receipts[key] = {'reported':reported,'process':receipt}
    return receipts


def pixels(path, background):
    path = regular(path)
    require(0 < path.stat().st_size <= MAX_PNG, 'PNG size exceeds bounded raw capture')
    before = authored.sha256(path)
    with path.open('rb') as source:header = source.read(26)
    require(header[:8] == b'\x89PNG\r\n\x1a\n' and header[24:26] == bytes((8,6)), 'expected RGBA8 PNG header')
    with Image.open(path) as image:
        require(image.format == 'PNG' and image.mode == 'RGBA' and image.size == EXTENT,
                'expected unscaled 960x540 RGBA8 capture')
        image.load()
        require(image.getchannel('A').getextrema() == (255,255), 'static capture must have opaque alpha')
        raw = image.tobytes()
    check = verify_png(path, EXTENT, background, .01, 8, None)
    require(authored.sha256(path) == before, 'PNG changed during read-only comparison')
    return raw, {'png_sha256': before, 'rgba_sha256': hashlib.sha256(raw).hexdigest(), 'image_check': check}


def validate_capture(folder, role, pose, logs):
    folder = Path(folder);image = folder / f'{pose}.png'
    expected = {image.name + s for s in ('', '.json', '.lighting.json', '.world.png')}
    if role == 'current':expected.add(image.name + '.world.png.json')
    require(folder.is_dir() and not folder.is_symlink()
            and {p.name for p in folder.iterdir()} == expected, 'missing or unexpected comparison captures')
    metadata = read_record(regular(Path(str(image)+'.json')))
    expected_fields = COMMON_FIELDS | (authored.RENDERER_IDENTITY if role == 'current' else frozenset())
    require(set(metadata) == expected_fields, 'unexpected presentation JSON fields or witness')
    require(metadata['capture']=='native offscreen viewmodel' and metadata['reload_phase'] is None,
            'not a frozen static viewmodel capture')
    for key,value in (('width',960),('height',540)):
        require(type(metadata[key]) is int and metadata[key]==value, 'wrong reference extent')
    for key,value in (('hfov',76),('ads',int(pose == 'ads'))):
        require(type(metadata[key]) in (int,Decimal) and metadata[key]==value, 'wrong frozen reference framing')
    light = authored.validate_lighting_record(regular(Path(str(image)+'.lighting.json')))
    require(light['simulation_time'] == 0 and light['yaw_degrees'] == -90 and light['pitch_degrees'] == 0,
            'static time or camera is not frozen')
    text = '\n'.join(regular(Path(logs)/n).read_text(encoding='utf-8', errors='replace')
                     for n in ('stdout.log','stderr.log'))
    require('Loaded VRMESH01 weapon: 30 mesh parts' in text and 'could not load' not in text.casefold(),
            'approved static weapon did not load')
    if role == 'current':
        adapter = native.legacy_renderer_logs(logs)['adapter']
        require(metadata.get('requested') == 'gl' and metadata.get('backend') == 'OpenGl'
                and metadata.get('adapter') == adapter, 'current backend/adapter identity differs')
        world = read_record(regular(Path(str(image)+'.world.png.json')))
        require(world.get('capture') == 'native window' and world.get('backend') == 'OpenGl'
                and world.get('requested') == 'gl' and world.get('adapter') == adapter
                and (world.get('width'),world.get('height')) == EXTENT, 'current world identity differs')
    else:adapter = None  # Original source has only Macroquad GL and does not log an adapter.
    checks = {}
    for name,bg in (('viewmodel',authored.BACKGROUND),('world',authored.WORLD_BACKGROUND)):
        _,checks[name] = pixels(image if name == 'viewmodel' else Path(str(image)+'.world.png'), bg)
    return {'role':role, 'pose':pose, 'image_checks':checks, 'adapter':adapter,
            'adapter_reported':role == 'current', 'loaded_modules_verified':False}


def pixel_difference(before, after, background):
    left,lmeta = pixels(before, background);right,rmeta = pixels(after, background)
    maxima, sums, count, first, bounds = [0]*4, [0]*4, 0, None, None
    for offset in range(0,len(left),4):
        a,b = left[offset:offset+4],right[offset:offset+4]
        if a == b:continue
        y,x = divmod(offset//4,EXTENT[0]);count += 1
        if first is None:first = {'xy':[x,y], 'reference':list(a), 'current':list(b)}
        bounds = [x,y,x,y] if bounds is None else [min(bounds[0],x),min(bounds[1],y),max(bounds[2],x),max(bounds[3],y)]
        for c in range(4):
            delta = abs(a[c]-b[c]);maxima[c] = max(maxima[c],delta);sums[c] += delta
    return {'exact_rgba_equal':count == 0, 'changed_pixels':count, 'pixels':EXTENT[0]*EXTENT[1],
            'maximum_absolute_channel_difference':maxima, 'sum_absolute_channel_difference':sums,
            'changed_bounds_inclusive':bounds, 'first_difference':first,
            'reference':lmeta, 'current':rmeta, 'tolerance_applied':False}


def compare_pose(reference, current, pose):
    before,after = Path(reference)/f'{pose}.png',Path(current)/f'{pose}.png'
    a,b = read_record(Path(str(before)+'.json')),read_record(Path(str(after)+'.json'))
    differences, numeric_representation = [], []
    for key in sorted(COMMON_FIELDS):
        try:_compare(a[key], b[key], f'presentation[{key!r}]')
        except ValueError as error:
            differences.append(str(error))
            if type(a[key]) in (int,Decimal) and type(b[key]) in (int,Decimal) and a[key] == b[key]:
                numeric_representation.append(key)
    light_a,light_b = read_record(Path(str(before)+'.lighting.json')),read_record(Path(str(after)+'.lighting.json'))
    try:_compare(light_a,light_b,'lighting')
    except ValueError as error:differences.append(str(error))
    images = {name:pixel_difference(before if name == 'viewmodel' else Path(str(before)+'.world.png'),
                                   after if name == 'viewmodel' else Path(str(after)+'.world.png'),bg)
              for name,bg in (('viewmodel',authored.BACKGROUND),('world',authored.WORLD_BACKGROUND))}
    return {'pose':pose, 'shared_json_equal':not differences, 'json_differences':differences,
            'numeric_representation_only_fields':numeric_representation,
            'shared_presentation_fields':sorted(COMMON_FIELDS), 'all_lighting_fields_compared':True,
            'images':images, 'exact_bounded_match':not differences and all(v['exact_rgba_equal'] for v in images.values())}


def run(reference_zip, executable, root, runtime, evidence, timeout=180):
    require(sys.platform == 'win32', 'facade comparison requires native Windows')
    require(type(timeout) in (int,float) and 0 < timeout <= 900, 'timeout must be within0..900 seconds')
    paths = [Path(p) for p in (reference_zip,executable,root,runtime,evidence)]
    for path,kind in zip(paths[:-1],('file','file','directory','directory')):
        shards._checked_stat(path,kind)
    if paths[-1].exists() or paths[-1].is_symlink():raise ValueError('fresh evidence required')
    reference_zip,executable,root,runtime,evidence = [p.resolve() for p in paths]
    require(root.is_dir() and not evidence.exists(), 'source directory and fresh evidence required')
    context = shards.context()
    require(os.environ.get('GITHUB_REPOSITORY') == REFERENCE['repository'], 'wrong workflow repository')
    source = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    require(source == context['source_commit'], 'source differs from workflow revision')
    subprocess.run(['git','diff','--exit-code','HEAD','--','src','tools','build.rs','build_number.rs',
                    'Cargo.toml','Cargo.lock','updater'],cwd=root,check=True,capture_output=True)
    evidence.mkdir(parents=True,exist_ok=False)
    report = {'schema':SCHEMA, 'status':'running', 'passed':False, 'binding':context,
              'checks':[], 'captures':[], 'comparisons':[], 'loaded_modules_verified':False,
              'scope':'Only frozen pre-facade/current GL hip/ADS world and viewmodel captures. No global sameness, human approval or full authored-suite claim.'}
    def check(name, action):
        try:result = action();row = {'name':name,'passed':True,'result':result}
        except Exception as error:row = {'name':name,'passed':False,'error':f'{type(error).__name__}: {error}'}
        report['checks'].append(row);authored.write_json(evidence/'summary.json',report)
        return row['passed']
    frozen = {};stage = evidence/'runtime';source_asset = root/'assets/weapons/hk416a5.vrm'
    asset = evidence/'inputs/hk416a5.vrm';settings = evidence/'settings.cfg'
    def inputs():
        regular(executable);regular(source_asset)
        require(0 < executable.stat().st_size <= MAX_EXE, 'invalid current executable size')
        require(authored.sha256(source_asset) == calibrated.ASSET_SHA256, 'wrong approved static weapon')
        asset_bytes = source_asset.read_bytes()
        require(hashlib.sha256(asset_bytes).hexdigest() == calibrated.ASSET_SHA256, 'weapon changed while reading')
        info = vrpack.inspect_vrm(asset_bytes)
        require(info['crc32'] == 'fc786964' and info['meshes'] == 30 and info['textures'] == 0
                and info['texture_bytes'] == 0, 'wrong untextured weapon structure')
        old = reference_executable(reference_zip,evidence/'reference-input')
        asset.parent.mkdir();write_bytes_exclusive(asset,asset_bytes)
        write_bytes_exclusive(settings,calibrated.SETTINGS)
        current_sha = authored.sha256(executable)
        runtime_record = stage_runtime(executable,runtime,root/'tools/windows_gl_reference_lock.json',stage)
        write_bytes_exclusive(stage/'reference-vector-range.exe',(evidence/'reference-input/vector-range.exe').read_bytes())
        require(authored.sha256(stage/'vector-range.exe')==current_sha and authored.sha256(executable)==current_sha,
                'current EXE changed during staging')
        require(authored.sha256(stage/'reference-vector-range.exe')==old['identity']['executable']['sha256'],
                'historical EXE changed during staging')
        frozen.update(shards.inventory_files(stage,exclude=()))
        report['binding'].update(current_executable_sha256=current_sha,
            reference_executable_sha256=old['identity']['executable']['sha256'],
            asset_sha256=calibrated.ASSET_SHA256,settings_sha256=authored.sha256(settings),
            reference=old,runtime=runtime_record,documented_framing=calibrated.DOCUMENTED_FRAMING)
        authored.write_json(evidence/'input-manifest.json',report['binding'])
        return old
    ready = check('validated-inputs',inputs)
    if ready:
        def identities():
            current = build_identity.context()
            require(current['source']['commit']==source, 'embedded identity expectation differs from checkout')
            with runtime_environment():
                return {role:embedded_identity(stage/name,stage,evidence/'logs'/f'{role}-identity',expected)
                        for role,name,expected in (('reference','reference-vector-range.exe',REFERENCE_IDENTITY),
                                                   ('current','vector-range.exe',current))}
        ready = check('verified-executable-identities',identities)
    if ready:
        with runtime_environment():
            for role in ('reference','current'):
                for pose in ('hip','ads'):
                    folder = evidence/'captures'/f'{role}-{pose}';folder.mkdir(parents=True)
                    logs = evidence/'logs'/f'{role}-{pose}'
                    exe = stage/('reference-vector-range.exe' if role == 'reference' else 'vector-range.exe')
                    argv = command(exe,asset,settings,folder/f'{pose}.png',role,pose)
                    def capture(folder=folder,logs=logs,argv=argv,role=role,pose=pose):
                        authored.execute(argv,stage,logs,timeout)
                        receipt = process_record(logs,argv,stage)
                        require(process_receipt(logs,900,1) == argv, 'capture receipt changed invocation')
                        result = validate_capture(folder,role,pose,logs)
                        result['process'] = receipt;report['captures'].append(result);return result
                    check(f'{role}-{pose}',capture)
        for pose in ('hip','ads'):
            def compare(pose=pose):
                require(all(any(r['role']==role and r['pose']==pose for r in report['captures'])
                            for role in ('reference','current')), 'both validated captures required')
                result = compare_pose(evidence/'captures'/f'reference-{pose}',evidence/'captures'/f'current-{pose}',pose)
                report['comparisons'].append(result);return result
            check(f'{pose}-comparison',compare)
        def unchanged():
            require(authored.sha256(reference_zip)==REFERENCE['zip_sha256'], 'historical ZIP changed')
            require(authored.sha256(executable)==report['binding']['current_executable_sha256'], 'current EXE changed')
            require(authored.sha256(asset)==calibrated.ASSET_SHA256
                    and authored.sha256(source_asset)==calibrated.ASSET_SHA256
                    and settings.read_bytes()==calibrated.SETTINGS,
                    'weapon/settings changed')
            shards.verify_files(stage,frozen,exclude=())
            validate_runtime(stage,root/'tools/windows_gl_reference_lock.json')
            return {'inputs_unchanged':True}
        check('inputs-unchanged',unchanged)
    valid = len(report['checks']) == 9 and all(c['passed'] for c in report['checks'])
    report['comparison_complete'] = valid
    report['passed'] = valid and len(report['comparisons']) == 2 and all(c['exact_bounded_match'] for c in report['comparisons'])
    report['status'] = 'passed' if report['passed'] else ('differences-observed' if valid else 'failed')
    try:report['files'] = shards.inventory_files(evidence)
    except (OSError,ValueError) as error:
        report.update(passed=False,status='failed',files={},inventory_error=str(error))
    authored.write_json(evidence/'summary.json',report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reference-zip','executable','root','runtime','evidence'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=180)
    try:result = run(**vars(parser.parse_args(argv)))
    except (OSError,ValueError,subprocess.SubprocessError,zipfile.BadZipFile) as error:
        parser.exit(1,f'Legacy facade comparison failed: {error}\n')
    print(json.dumps(result,indent=2,allow_nan=False))
    # Differences are retained for scoped review, never silently declared equal.
    return 0 if result['passed'] else 1


if __name__ == '__main__':raise SystemExit(main())
