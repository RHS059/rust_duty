#!/usr/bin/env python3
"""Verify independently pinned, terminal deterministic60/30 native captures."""
import argparse,json
from pathlib import Path
from run_high_mantle_deterministic import verified_config,invocation
from verify_high_mantle_observer import need,read,sha,safe_path
from verify_high_mantle_deterministic import verify

def verify_run(folder,config,config_sha):
    c,root,identity=verified_config(config,config_sha);folder=Path(folder).resolve();run=read(folder/'run.json')
    need(run['schema']=='rust-duty-onehand-deterministic-run/v1' and run['config_sha256']==config_sha,'run/config mismatch')
    need(run['frame_witness']==identity and run['native_platform']=='Linux' and not run['windows_dx12_verified'],'identity/platform mismatch')
    need(run['input_route']=='deterministic_ordinary_input' and run['real_platform_hotkeys'] is False,'wrong input label')
    need(run.get('inputs_unchanged') is True and run.get('capture_processes_completed') is True,'run incomplete')
    need(run['runs'] and len({r['hz'] for r in run['runs']})==len(run['runs']),'empty/duplicate rates')
    results=[]
    for entry in run['runs']:
        hz=entry['hz'];need(hz in (30,60),'invalid rate')
        need(entry['exit_code']==0 and entry.get('completed') is True,'nonterminal rate')
        expected=invocation(safe_path(root,c['executable']),safe_path(root,c['manifest']),folder/str(hz)/'game',identity,hz)
        need(entry['command']==expected and run['commands'][str(hz)]==expected,'command changed')
        result=verify(folder/str(hz)/'game',c['binding'],hz,identity)
        result['game_log_sha256']=sha(folder/str(hz)/'game.log');results.append(result)
    verified_config(config,config_sha)
    return {'schema':'rust-duty-onehand-deterministic-verification/v1','run_sha256':sha(folder/'run.json'),
            'config_sha256':config_sha,'source_and_payload_pins_unchanged':True,'rates':results,
            'both_rates_verified':{r['sampling_hz'] for r in results}=={30,60},
            'platform_interruptions_verified':False,'windows_dx12_verified':False,
            'runtime_parity_reverified_here':False,'artistic_approval':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--report',type=Path,required=True);a=p.parse_args();need(not a.report.exists(),'report must be new')
    result=verify_run(a.run,a.config,a.config_sha256);a.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'both_rates_verified':result['both_rates_verified'],'platform_interruptions_verified':False}))
if __name__=='__main__':main()
