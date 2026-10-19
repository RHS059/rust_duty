#!/usr/bin/env python3
"""Bind terminal telemetry/PNGs to independently pinned source/build/input bytes."""
import argparse,json
from pathlib import Path
from run_high_mantle_inputs import verified_config,invocation
from verify_high_mantle_observer import need,read,sha,safe_path,verify

def verify_run(folder,config,config_sha):
    c,root,identity=verified_config(config,config_sha);folder=Path(folder).resolve();run=read(folder/'run.json')
    need(run['schema']=='rust-duty-onehand-native-input-run/v1' and run['config_sha256']==config_sha,'run/config mismatch')
    need(run['frame_witness']==identity and run['native_platform']=='Linux' and not run['windows_dx12_verified'],'invocation/platform mismatch')
    need(run.get('inputs_unchanged') is True and run.get('capture_processes_completed') is True,'run incomplete')
    need(run['runs'] and len({x['scenario'] for x in run['runs']})==len(run['runs']),'empty/duplicate run')
    results=[]
    for entry in run['runs']:
        scenario=entry['scenario'];need(scenario in ('complete','cancel','reset','debug-death'),'unknown scenario')
        need(entry['exit_code']==0 and entry.get('completed') is True,'nonterminal scenario')
        expected=invocation(safe_path(root,c['executable']),safe_path(root,c['manifest']),folder/scenario/'game',identity)
        need(entry['command']==expected and run['commands'][scenario]==expected,'command changed')
        result=verify(folder/scenario/'game',c['binding'],scenario,identity)
        result['platform_input_log_sha256']=sha(folder/scenario/'platform-inputs.jsonl');results.append(result)
    verified_config(config,config_sha)
    return {'schema':'rust-duty-onehand-native-input-verification/v1','run_sha256':sha(folder/'run.json'),
            'config_sha256':config_sha,'source_and_payload_pins_unchanged':True,'scenarios':results,
            'complete_scenario_set':{r['scenario'] for r in results}=={'complete','cancel','reset','debug-death'},
            'windows_dx12_verified':False,'runtime_parity_reverified_here':False,'artistic_approval':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    need(not a.report.exists(),'report must be new');report=verify_run(a.run,a.config,a.config_sha256)
    a.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'scenarios':[x['scenario'] for x in report['scenarios']],
                      'complete_scenario_set':report['complete_scenario_set'],'windows_dx12_verified':False}))
if __name__=='__main__':main()
