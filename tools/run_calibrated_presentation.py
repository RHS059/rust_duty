#!/usr/bin/env python3
"""Run four source-bound Windows static HK416 calibration captures, without rebuilding.

The ordinary authored suite remains required. No geometry, framing, calibration,
asset bindings or gameplay code is changed. Existing app-local Mesa is reused.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import dx12_authored_shards as shards
import run_dx12_authored as authored
import run_dx12_authored_shard as native
from run_windows_same_platform_return import stage_runtime, runtime_environment, regular
from verify_capture_telemetry import read_record
import verify_calibrated_presentation as validator
import vrpack


def command(executable, asset, settings, folder, backend, pose, expected_identity):
    validator.require(backend in ('OpenGl','Dx12') and pose in validator.TARGETS, 'unknown static capture')
    result = [str(executable), '--renderer=' + ('dx12' if backend == 'Dx12' else 'gl'),
              '--no-update', '--reference-viewport', '--profile=kestrel',
              f'--weapon-asset={asset}', f'--settings={settings}', '--capture', '--capture-lighting',
              f'--output={folder / (pose + ".png")}', f'--capture-frame-witness={expected_identity}']
    if backend == 'Dx12':result.append('--force-fallback-adapter')
    if pose == 'ads':result.append('--capture-ads')
    return result


def native_receipt(logs, expected_command, root):
    invocation = read_record(logs/'invocation.json');process = read_record(logs/'process.json')
    validator.require(invocation.get('command') == expected_command and invocation.get('cwd') == str(root), 'changed native invocation')
    validator.require(process.get('status') == 'passed' and type(process.get('exit_code')) is int and process['exit_code'] == 0,
                      'native process did not complete cleanly')
    # execute counts the explicit output file; folder inventory separately
    # requires the additional world checkpoint.
    validator.require(type(process.get('png_files')) is int and process['png_files'] == 1, 'native process must complete the explicit reference output file')
    text='\n'.join((logs/name).read_text(encoding='utf-8',errors='replace') for name in ('stdout.log','stderr.log'))
    validator.require('Loaded VRMESH01 weapon: 30 mesh parts' in text, 'static approved weapon did not load')
    validator.require('could not load' not in text.casefold(), 'asset loading error in native log')


def run(executable, root, runtime, evidence, timeout=180):
    validator.require(sys.platform == 'win32', 'calibrated native acceptance requires Windows')
    validator.require(type(timeout) in (int,float) and 0 < timeout <= 900, 'timeout must be within 0..900 seconds')
    for path in (executable,root,runtime,evidence):
        validator.require(not Path(path).is_symlink(), 'symlinked fixture path')
    executable,root,runtime,evidence = map(lambda p:Path(p).resolve(),(executable,root,runtime,evidence))
    validator.require(not evidence.exists(), 'refusing existing fixture evidence')
    evidence.mkdir(parents=True)
    report={'schema':validator.SCHEMA,'status':'running','passed':False,'checks':[],'measurements':[],
            'scope':'Documented calibrated static HK416 path only; every authored replay/contact gate remains required',
            'human_visual_gate':'open','hardware_playtest_gate':'open'}
    def save():authored.write_json(evidence/'summary.json',report)
    def check(name, action):
        try:result=action();row={'name':name,'passed':True,'result':result}
        except Exception as error:row={'name':name,'passed':False,'error':f'{type(error).__name__}: {error}'}
        report['checks'].append(row);save();return row['passed']
    save();binding=None;asset=None;settings=None;local=None;frozen=None
    def inputs():
        nonlocal binding,asset,settings,local,frozen
        context=shards.context()
        actual=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
        validator.require(actual==context['source_commit'],'checkout does not match this GitHub source revision')
        subprocess.run(['git','diff','--exit-code','--','src','Cargo.toml','Cargo.lock','tools'],cwd=root,check=True,capture_output=True)
        regular(executable)
        asset=regular(root/'assets/weapons/hk416a5.vrm')
        validator.require(authored.sha256(asset)==validator.ASSET_SHA256,'wrong calibrated weapon asset')
        info=vrpack.inspect_vrm(asset.read_bytes())
        validator.require(info['crc32']=='fc786964' and info['meshes']==30 and info['textures']==0 and info['texture_bytes']==0,
                          'asset is not the exact approved untextured static weapon')
        settings=evidence/'calibration-settings.cfg';settings.write_bytes(validator.SETTINGS)
        staged=stage_runtime(executable,runtime,root/'tools/windows_gl_reference_lock.json',evidence/'gl-runtime')
        local=evidence/'gl-runtime/vector-range.exe'
        binding={**context,'executable_sha256':authored.sha256(executable),'asset_sha256':validator.ASSET_SHA256,
                 'settings_sha256':authored.sha256(settings),'documented_default_framing':dict(validator.DOCUMENTED_FRAMING),
                 'profile':'kestrel','platform':'win32','runtime':staged}
        frozen=shards.inventory_files(evidence/'gl-runtime',exclude=())
        report['binding']=binding
        authored.write_json(evidence/'input-manifest.json',binding)
        return {'binding':binding,'asset_inspection':info}
    ready=check('validated-static-inputs',inputs)
    if ready:
        with runtime_environment():
            for backend in ('OpenGl','Dx12'):
                for pose in ('hip','ads'):
                    name=backend.lower()+'-'+pose;folder=evidence/'captures'/name;folder.mkdir(parents=True)
                    logs=evidence/'logs'/name;expected=validator.identity(binding,backend,pose)
                    argv=command(local,asset,settings,folder,backend,pose,expected)
                    def capture(argv=argv,logs=logs,folder=folder,backend=backend,pose=pose,expected=expected):
                        authored.execute(argv,root,logs,timeout,renderer=backend=='Dx12')
                        native_receipt(logs,argv,root)
                        if backend=='OpenGl':native.legacy_renderer_logs(logs)
                        result=validator.validate_capture(folder,backend,pose,expected)
                        result['capture_relative_path']=(folder/(pose+'.png')).relative_to(evidence).as_posix()
                        report['measurements'].append(result)
                        return result
                    check(name,capture)
        def comparison():
            result=validator.paired_results(report['measurements']);report['comparison']=result
            validator.require(result['passed'],'one or more static landmarks are outside original per-axis ±4px calibration')
            return result
        check('original-calibration-and-separate-paired-deltas',comparison)
        def immutable():
            validator.require(authored.sha256(executable)==binding['executable_sha256'],'input executable changed')
            validator.require(authored.sha256(asset)==binding['asset_sha256'],'calibration asset changed')
            validator.require(authored.sha256(settings)==binding['settings_sha256'],'settings changed')
            shards.verify_files(evidence/'gl-runtime',frozen,exclude=())
            return {'inputs_unchanged':True}
        check('inputs-unchanged',immutable)
    report['passed']=len(report['checks'])==7 and all(row['passed'] for row in report['checks'])
    report['status']='passed' if report['passed'] else 'failed'
    authored.write_json(evidence/'measurement-packet.json',{'schema':validator.SCHEMA,'binding':binding,
        'measurements':report['measurements'],'comparison':report.get('comparison'),
        'scope':report['scope'],'human_visual_gate':'open','hardware_playtest_gate':'open'})
    try:report['files']=shards.inventory_files(evidence)
    except Exception as error:
        report.update(passed=False,status='failed',files={},inventory_error=str(error))
    save();return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('executable','root','runtime','evidence'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=180)
    args=parser.parse_args()
    try:result=run(args.executable,args.root,args.runtime,args.evidence,args.timeout)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        print(f'Calibrated presentation failed: {error}',file=sys.stderr);return 1
    print(json.dumps(result,indent=2,allow_nan=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
