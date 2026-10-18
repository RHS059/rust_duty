"""Read-only native admission, completed before any Blender/Rust installer.

Only a wholly absent/null admission is ordinary blocked WIP. A partial, malformed
or contradictory non-null record is an error. No unknown expected identity is
inferred from observed source/test output, and no completion flag substitutes for
actual source/reference/transport verification.
"""
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
sys.dont_write_bytecode=True
ROOT=Path(__file__).absolute().parent
sys.path.insert(0,str(ROOT))
from workflow_core import *
import projection_binding
import checkout_bytes,orchestrate,source_selection

SCHEMA='rust-duty-onehand-native-source-admission/v4'
ADMISSION_PATH='tools/onehand_windows/proof-admission.json'
FIELDS={'schema','orchestration_pins_sha256','proof_inputs','controller_layout','independent_review'}

def admission_state(value):
    if value is None:return 'blocked-incomplete-admission'
    require(type(value) is dict and set(value)==FIELDS and value['schema']==SCHEMA,'native source admission fields/schema differ')
    values=[value[k] for k in FIELDS-{'schema'}]
    if all(v is None for v in values):return 'blocked-incomplete-admission'
    sha_value(value['orchestration_pins_sha256'])
    for name in ('proof_inputs','controller_layout','independent_review'):
        row=value[name];require(type(row) is dict and set(row)=={'ref','repository_path','sha256','bytes'},'complete independently reviewed input reference required')
        require(type(row['ref']) is str and re.fullmatch('[0-9a-f]{40}',row['ref']),'actual immutable reviewed commit required')
        checkout_bytes.relative(row['repository_path']);sha_value(row['sha256'])
        require(type(row['bytes']) is int and 0<row['bytes']<=8*1024**2,'bounded exact reviewed input bytes')
    return 'requires-full-input-verification'

def verify_acceptance(value,expected_package,expected_dependencies,expected_inputs,expected_layout):
    require(type(value) is dict and set(value)=={'schema','decision','orchestration_pins_sha256','reviewed_dependencies_sha256','proof_inputs_sha256','controller_layout_sha256','source_transport_parts_sha256','rust_source_selection_sha256','source_projection_sha256','metadata_recipe_sha256','blocking_findings','animation_proof'},'independent acceptance fields differ')
    require(value['schema']=='rust-duty-onehand-workflow-independent-acceptance/v4' and value['decision']=='accepted-for-guarded-native-proof','actual independent native workflow acceptance required')
    require(value['orchestration_pins_sha256']==expected_package and value['reviewed_dependencies_sha256']==expected_dependencies,'independent acceptance identities differ')
    require(value['proof_inputs_sha256']==expected_inputs and value['controller_layout_sha256']==expected_layout,'independent completed input/layout acceptance differs')
    require(value['source_transport_parts_sha256']==checkout_bytes.PARTS_MANIFEST_SHA and value['rust_source_selection_sha256']==source_selection.SELECTION_SHA,'independent exact source transport/selection acceptance differs')
    require(value['source_projection_sha256']==projection_binding.PROJECTION_SHA and value['metadata_recipe_sha256']==projection_binding.METADATA_RECIPE_SHA,'independent explicit metadata projection acceptance differs')
    require(value['blocking_findings']==[] and value['animation_proof'] is False,'independent review unresolved or misrepresented as animation proof')

def checked_fetch(row,reader):
    raw=reader(row['ref'],row['repository_path'],row['bytes'])
    require(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'independently expected Git source bytes differ');return raw

def validate_proof_sources(root,layout,checkout,review):
    require(layout['schema']=='rust-duty-onehand-controller-layout/v1','controller layout schema differs')
    require(set(layout)=={'schema','roots','inputs','authored_bridge','rust_features'},'controller layout fields differ')
    def rel(value):return ordinary(root/checkout_bytes.relative(value),True)
    config={'roots':{k:str(rel(v)) for k,v in layout['roots'].items()},'inputs':{k:str(rel(v)) for k,v in layout['inputs'].items()},'authored_bridge':str(rel(layout['authored_bridge']))}
    require(set(config['roots'])=={'audited_source','source_package','reference','context_package','process_adapter','native_producer','runtime_consumer','rust_source'},'source root role inventory differs')
    require(set(config['inputs'])=={'baseline','original_delta','canonical','transport_review','transport_smoke','transport_smoke_summary'},'source input role inventory differs')
    p=orchestrate.load_packages(config,review)
    args=orchestrate.bridge_arguments(config,review);recipe=p.bridge.verify_inputs(p.source,args);p.bridge.verify_reference(p.source,args,recipe)
    p.source.portable.cache_free_execution_package(p.source.core.package)
    expected={'transport_review':orchestrate.REVIEW_SHA,'transport_smoke':orchestrate.SMOKE_SHA,'transport_smoke_summary':orchestrate.SUMMARY_SHA}
    files={k:file_pin(pin(config['inputs'][k],h)) for k,h in expected.items()}
    ctx=SimpleNamespace(cc=p.cc,raw={'dependencies':{'transport_pins_sha256':orchestrate.TRANSPORT_SHA,'transport_review_sha256':orchestrate.REVIEW_SHA}},root=lambda role:Path(config['roots'][role]),pin=lambda role:p.cc.FilePin.parse(role,files[role]))
    p.native.transport_binding.verify_transport(ctx,production=True)
    delta_rows=[r for r in checkout['files'] if r['kind']=='original-action-delta']
    require(len(delta_rows)==1 and delta_rows[0].get('transport',{}).get('manifest_repository_path',delta_rows[0]['repository_path'])==review['published_original_delta_path'],'exact reviewed original-delta publication path required')
    source=Path(config['roots']['rust_source']);before=inventory(source)
    rows={r['destination'][len('rust-source/'):]:r['sha256'] for r in checkout['files'] if r['destination'].startswith('rust-source/') and r['ref']==review['rust_source_revision']}
    require(before==rows,'all Rust source bytes must match the independently selected actual commit')
    source_selection.verify(before,review['rust_source_revision'],layout['rust_features'])
    for name,h in p.consumer.pinned_math.read(p.consumer.pinned_math.HERE/'RUST_REFERENCE_PINS.json').items():require(before.get(name)==h,'reviewed Rust compiler input source differs')
    require(type(layout['rust_features']) is list and all(type(v) is str for v in layout['rust_features']) and len(set(layout['rust_features']))==len(layout['rust_features']),'explicit unique reviewed features required')
    return config

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--git',required=True);ap.add_argument('--repository',required=True);ap.add_argument('--event-commit',required=True);ap.add_argument('--work-root',required=True);ap.add_argument('--summary',required=True);ap.add_argument('--github-output',required=True);a=ap.parse_args()
    work=ordinary(a.work_root);summary={'schema':'rust-duty-onehand-pr-native-admission/v2','event_commit':a.event_commit,'status':'failed','source_test_only':True,'native_execution_performed':False,'animation_proof':False};status=1
    try:
        require(re.fullmatch('[0-9a-f]{40}',a.event_commit),'immutable exact event SHA required')
        kind=subprocess.run([a.git,'-C',a.repository,'cat-file','-t',a.event_commit],capture_output=True,check=True,timeout=60);require(kind.stdout.strip()==b'commit','actual event Git commit required')
        listing=subprocess.run([a.git,'-C',a.repository,'ls-tree','--name-only',a.event_commit,'--',ADMISSION_PATH],capture_output=True,check=True,timeout=60)
        reader=checkout_bytes.git_blob_reader(a.git,a.repository);admission=None
        if listing.stdout.strip():
            size=subprocess.run([a.git,'-C',a.repository,'cat-file','-s',a.event_commit+':'+ADMISSION_PATH],capture_output=True,check=True,timeout=60)
            require(size.stdout.strip().isdigit() and int(size.stdout.strip())<=1024**2,'admission source byte cap')
            path=work/'admission-source.json';path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as f:f.write(reader(a.event_commit,ADMISSION_PATH,int(size.stdout.strip())))
            admission=strict_json(path)
        state=admission_state(admission);summary['status']=state
        if state=='blocked-incomplete-admission':
            with Path(a.github_output).open('a',encoding='utf-8') as f:f.write('native_ready=false\n')
            status=0;return status
        expected=admission['orchestration_pins_sha256'];package(ROOT,expected)
        # All fields, including delta destination/Rust commit/toolchain, must be
        # independently populated before reading any native input or installer.
        review=orchestrate.reviewed_dependencies()
        review_path=work/'independent-review.json'
        with review_path.open('xb') as f:f.write(checked_fetch(admission['independent_review'],reader))
        verify_acceptance(strict_json(review_path),expected,sha(ROOT/'reviewed-dependencies.json'),admission['proof_inputs']['sha256'],admission['controller_layout']['sha256'])
        manifest=work/'proof-inputs.json';layout_path=work/'controller-layout.json'
        for name,path in (('proof_inputs',manifest),('controller_layout',layout_path)):
            with path.open('xb') as f:f.write(checked_fetch(admission[name],reader))
        root=work/'full-materialized';checkout=checkout_bytes.materialize(strict_json(manifest,8*1024**2),root,reader)
        checkout_path=work/'byte-checkout.json';write_new(checkout_path,checkout)
        package(root/'orchestration',expected)
        layout=strict_json(layout_path);validate_proof_sources(root,layout,checkout,review)
        require(sha(root/'controller-layout.json')==admission['controller_layout']['sha256'],'full materialized controller layout differs')
        bindings={'schema':'rust-duty-onehand-accepted-pr-bindings/v2','event_commit':a.event_commit,'package_pins_sha256':expected,'materialized_root':str(root),'package_root':str(root/'orchestration'),'layout':file_pin(layout_path),'byte_checkout':file_pin(checkout_path),'independent_review':record(review_path),'proof_inputs':record(manifest),'reviewed_dependencies':file_pin(ROOT/'reviewed-dependencies.json')}
        write_new(work/'accepted-bindings.json',bindings)
        summary.update(status='admitted-before-native-installers',source_test_only=False,orchestration_pins_sha256=expected,independent_review_sha256=admission['independent_review']['sha256'],proof_inputs_sha256=admission['proof_inputs']['sha256'],controller_layout_sha256=admission['controller_layout']['sha256'])
        with Path(a.github_output).open('a',encoding='utf-8') as f:f.write('native_ready=true\n')
        status=0;return status
    except Exception as exc:
        summary.update(status='failed',error_type=type(exc).__name__,error_sha256=hashlib.sha256(str(exc).encode()).hexdigest());return 1
    finally:
        write_new(Path(a.summary),summary,cap=128*1024);print(json.dumps(summary,sort_keys=True))
if __name__=='__main__':raise SystemExit(main())
