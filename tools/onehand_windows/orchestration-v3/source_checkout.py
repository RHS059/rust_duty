"""PR source tests only: materialize exact declared source blobs from event commit.

An observed package digest is diagnostic, never native proof acceptance. Native
execution separately requires the independent committed admission pins.
"""
import argparse,hashlib,json,subprocess,sys,types
from pathlib import Path
PACKAGE='tools/onehand_windows/orchestration-v3'
MATERIALIZER_SHA='90cc3d18daa0f703eb41a9ed8ca7a61f1487507ee234ad43826af918bc26ea80'

def require(v,m):
    if not v:raise ValueError(m)

def loads(raw):
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'duplicate JSON key');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs)

def export(git,repository,commit,path,cap):
    kind=subprocess.run([git,'-C',str(repository),'cat-file','-t',commit],capture_output=True,check=True,timeout=60)
    require(kind.stdout.strip()==b'commit','event SHA must be an actual Git commit')
    size=subprocess.run([git,'-C',str(repository),'cat-file','-s',commit+':'+path],capture_output=True,check=True,timeout=60)
    require(size.stdout.strip().isdigit() and int(size.stdout.strip())<=cap,'source blob cap')
    raw=subprocess.run([git,'-C',str(repository),'cat-file','blob',commit+':'+path],capture_output=True,check=True,timeout=60).stdout
    require(len(raw)==int(size.stdout.strip()),'source blob size changed');return raw

def source_rows(pins,layout,commit,pins_sha):
    require(layout['source_only'] is True and layout['private_or_held_payloads_included'] is False,'source-only layout required')
    rows=[]
    for item in layout['files']:
        if item['materialized_path'] is None:continue
        require(item['kind'] in ('original-source','hash-only-reference'),'held/private source input forbidden')
        expected=(pins_sha if item['source']=='PINS.json' else pins[item['source']]) if item['origin']=='orchestration' else item['sha256']
        rows.append({'ref':commit,'repository_path':item['repository_path'],'destination':item['materialized_path'],'sha256':expected,'kind':item['kind']})
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--git',required=True);p.add_argument('--repository',required=True);p.add_argument('--event-commit',required=True);p.add_argument('--materializer',required=True);p.add_argument('--output',required=True);p.add_argument('--receipt',required=True);a=p.parse_args()
    import re
    require(re.fullmatch('[0-9a-f]{40}',a.event_commit),'full immutable event commit required')
    helper=Path(a.materializer).read_bytes();require(hashlib.sha256(helper).hexdigest()==MATERIALIZER_SHA,'reviewed source materializer differs')
    mod=types.ModuleType('_exact_source_checkout');mod.__file__=a.materializer;exec(compile(helper,a.materializer,'exec'),mod.__dict__)
    raw=export(a.git,a.repository,a.event_commit,PACKAGE+'/PINS.json',1024**2);pins=loads(raw);observed=hashlib.sha256(raw).hexdigest()
    layout_raw=export(a.git,a.repository,a.event_commit,PACKAGE+'/PUBLICATION_LAYOUT.json',2*1024**2)
    require(hashlib.sha256(layout_raw).hexdigest()==pins['PUBLICATION_LAYOUT.json'],'declared source layout differs')
    rows=source_rows(pins,loads(layout_raw),a.event_commit,observed)
    for row in rows:
        size=subprocess.run([a.git,'-C',a.repository,'cat-file','-s',a.event_commit+':'+row['repository_path']],capture_output=True,check=True,timeout=60)
        require(size.stdout.strip().isdigit(),'source blob size missing');row['bytes']=int(size.stdout.strip())
    value=mod.materialize({'schema':'rust-duty-onehand-byte-materialization/v1','files':rows},Path(a.output),mod.git_blob_reader(a.git,a.repository))
    result={'schema':'rust-duty-onehand-source-test-checkout/v2','event_commit':a.event_commit,'observed_orchestration_pins_sha256':observed,'source_test_only':True,'native_execution_admitted':False,'checkout':value}
    with Path(a.receipt).open('xb') as f:f.write((json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode())
    print(json.dumps({'source_materialized':True,'source_test_only':True,'observed_orchestration_pins_sha256':observed},sort_keys=True))
if __name__=='__main__':
    try:main()
    except Exception as exc:print(json.dumps({'passed':False,'error_type':type(exc).__name__,'error_sha256':hashlib.sha256(str(exc).encode()).hexdigest()}));raise SystemExit(1)
