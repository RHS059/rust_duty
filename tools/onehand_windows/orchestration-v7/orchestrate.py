"""Sequential original-source -> native -> actual Rust one-hand proof controller.

Every successor pins actual already-completed predecessor bytes. No old context
is rewritten. Native/runtime validators are imported unchanged from reviewed
packages. No source geometry, raw witnesses or intermediate assets are uploaded.
"""
from __future__ import annotations
import argparse,copy,time,sys
from pathlib import Path
from types import SimpleNamespace
from workflow_core import *
import host_tools,build_rust,source_selection,projection_binding

CONTEXT_SHA='8702d486bc36a649924c3d844ea5eab445600f93995ec8367ea02d94e250c48a'
SOURCE_SHA='3b52a15fe761b9b1ae30b88caab7be132ad635f9aa2d070b6bb2f6d3133fbd71'
BRIDGE_SHA='bc995d517728052b5dc4694342b09dabb7466077746258f9513f234b439ceb05'
TRANSPORT_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
REVIEW_SHA='820c10f716aadfb3ee9f7e3e3c8e176b446df0568f4196dce4fd0b7c08cf6527'
SMOKE_SHA='0a10a58145fb2d6d9348ecc8a61d0ad2f8f318e7f644a9b46ce9716d386d6b17'
SUMMARY_SHA='b14b01a539920f34eec064a1bec1ec2799840c31e89a36e841831a3960c90fa2'


def reviewed_dependencies():
    v=strict_json(HERE/'reviewed-dependencies.json')
    require(v['schema']=='rust-duty-onehand-orchestration-review/v1','review schema differs')
    for key in ('native_producer_pins_sha256','runtime_consumer_pins_sha256','reference_replay_sha256','reference_index_sha256','reference_equivalence_sha256'):sha_value(v[key])
    require(type(v['published_original_delta_path']) is str and v['published_original_delta_path'] and '..' not in Path(v['published_original_delta_path']).parts and not Path(v['published_original_delta_path']).is_absolute(),'original delta publication/materialization path not reviewed')
    require(type(v['rust_source_revision']) is str and re.fullmatch('[0-9a-f]{40}',v['rust_source_revision']),'Rust source revision not reviewed')
    require(type(v['rust_toolchain']) is str and re.fullmatch(r'\d+\.\d+\.\d+-x86_64-pc-windows-msvc',v['rust_toolchain']),'exact Rust toolchain not reviewed')
    require(v['rust_source_revision']==source_selection.REVISION and v['rust_toolchain']==source_selection.TOOLCHAIN,'exact selected immutable Rust source and proposed toolchain required')
    return v

def load_packages(config,review):
    roots=config['roots'];package(roots['context_package'],CONTEXT_SHA);package(roots['source_package'],SOURCE_SHA)
    package(roots['native_producer'],review['native_producer_pins_sha256']);package(roots['runtime_consumer'],review['runtime_consumer_pins_sha256']);package(roots['process_adapter'],TRANSPORT_SHA,'transport')
    # No unpinned local module or cached bytecode is imported by these packages.
    cc=module('candidate_context',Path(roots['context_package'])/'candidate_context.py',{})
    native=modules(roots['native_producer'],('pinned_code','stage_context','transport_binding','planner','native_stages','process_evidence','admission','launch_stage'))
    consumer=modules(roots['runtime_consumer'],('pinned_math','build_closure','runtime_context','transport','evidence','retirement','consumer'))
    adapter=modules(roots['process_adapter'],('windows_job','owned_process')).owned_process
    bridge_path=pin(config['authored_bridge'],BRIDGE_SHA);bridge=module('authored_bridge',bridge_path,{})
    dependencies=bridge.load_dependencies(roots['source_package'])
    native.pinned_code.verify_originals(roots['audited_source']);consumer.pinned_math.load(roots['audited_source'])
    require(consumer.runtime_context.SELECTED_PRODUCER_PINS_SHA==review['native_producer_pins_sha256'],'consumer selected producer identity differs')
    require(consumer.runtime_context.REVIEWED_TRANSPORT_PINS_SHA==TRANSPORT_SHA,'consumer transport revision differs')
    return SimpleNamespace(cc=cc,native=native,consumer=consumer,adapter=adapter,bridge=bridge,source=dependencies)

def bridge_arguments(config,review):
    refs=ordinary(config['roots']['reference'],True)
    return SimpleNamespace(source_package=Path(config['roots']['source_package']),baseline=Path(config['inputs']['baseline']),delta=Path(config['inputs']['original_delta']),canonical=Path(config['inputs']['canonical']),reference_directory=refs,reference_replay_sha256=review['reference_replay_sha256'],reference_index_sha256=review['reference_index_sha256'],reference_proof_sha256=review['reference_equivalence_sha256'])

def prepare(config,review,packages):
    p=packages;cc=p.cc;root=ordinary(config['private_root']);candidate=root/config['session_id']/'candidates'/config['candidate_id']
    for k in ('candidate_id','session_id','runner_id','run_id'):cc.identifier(config[k],k)
    require(not candidate.exists(),'fresh candidate required; no automatic retry/overwrite')
    for value in config['roots'].values():
        path=ordinary(value,True);require(not path.is_relative_to(root) and not root.is_relative_to(path),'private and protected source roots overlap')
    require(config['rust']['source_revision']==review['rust_source_revision'] and config['rust']['toolchain']==review['rust_toolchain'],'reviewed Rust source/toolchain differs')
    checkout=strict_json(pin(config['byte_checkout']['path'],config['byte_checkout']['sha256']))
    delta_rows=[r for r in checkout['files'] if r['kind']=='original-action-delta']
    require(len(delta_rows)==1 and delta_rows[0].get('transport',{}).get('manifest_repository_path',delta_rows[0]['repository_path'])==review['published_original_delta_path'],'reviewed original delta publication path differs')
    args=bridge_arguments(config,review);recipe=p.bridge.verify_inputs(p.source,args);p.bridge.verify_reference(p.source,args,recipe)
    p.source.portable.cache_free_execution_package(p.source.core.package)
    fixed={'baseline':(config['inputs']['baseline'],cc.BASE_SHA),'original_delta':(config['inputs']['original_delta'],cc.DELTA_SHA),'canonical':(config['inputs']['canonical'],cc.CANONICAL_SHA),'source_grid':(str(Path(config['roots']['source_package'])/'dense-times.json'),cc.GRID_SHA),'reference_replay':(str(args.reference_directory/'replay-receipt.json'),review['reference_replay_sha256']),'reference_index':(str(args.reference_directory/'witness-index.json'),review['reference_index_sha256']),'reference_equivalence':(str(args.reference_directory/'source-equivalence.json'),review['reference_equivalence_sha256']),'transport_review':(config['inputs']['transport_review'],REVIEW_SHA),'transport_smoke':(config['inputs']['transport_smoke'],SMOKE_SHA),'transport_smoke_summary':(config['inputs']['transport_smoke_summary'],SUMMARY_SHA)}
    files={name:file_pin(pin(path,expected)) for name,(path,expected) in fixed.items()};unique_roles(files)
    capacity(root,8*GIB)
    return candidate,args,files

class Pipeline:
    def __init__(self,config,review,packages,candidate,args,files,host,commands):
        self.config=config;self.review=review;self.p=packages;self.candidate=candidate;self.args=args;self.files=dict(files);self.host=host;self.commands=commands;self.stages={};self.runtime=None
    def replay(self):
        c=self.candidate;source=c/'source'/'regenerated-onehand-v6.blend';receipt=c/'source'/'replay-receipt.json';source.parent.mkdir(parents=True)
        argv=self.p.source.core.runner.native_command(Path(self.config['roots']['blender_bundle'])/'blender.exe',['replay','--base',str(self.args.baseline),'--delta',str(self.args.delta),'--delta-sha256',self.p.cc.DELTA_SHA,'--output',str(source),'--receipt',str(receipt)])
        host_tools.verify_embedded(self.config)
        process=self.commands.run('source-replay',argv,c,reserve=96*1024**2)
        host_tools.verify_embedded(self.config)
        self.args.generated_source=source;self.args.generated_source_sha256=sha(source);self.args.target_replay=receipt;self.args.target_replay_sha256=sha(receipt)
        admission=self.p.bridge.admit_authored(self.p.source,self.args)
        self.files.update(generated_source=file_pin(source),target_replay=file_pin(receipt),authored_admission=write_new(c/'authored-admission.json',admission))
        write_new(c/'source'/'replay-process-link.json',{'schema':'rust-duty-windows-source-replay-process-link/v1','generated_source':self.files['generated_source'],'target_replay':self.files['target_replay'],'authored_admission':self.files['authored_admission'],'owned_process':process['terminal'],'argv':argv,'host':self.host,'cross_platform_evaluated_equality':False})
        self.lineage={'approved_source_sha256':self.p.cc.APPROVED_SHA,'source_package_pins_sha256':SOURCE_SHA,'action_hashes':admission['action_hashes'],'static_state_sha256':admission['static_state_sha256']}
    def native(self,stage,index=None,extra=None):
        n=self.p.native;stage_id=stage if index is None else f'{stage}-{index:03d}'
        roles=n.stage_context.COMMON|n.stage_context.INPUTS[stage];files={**self.files,**(extra or {})};require(roles<=set(files),'stage input missing')
        raw={'schema':n.stage_context.SCHEMA,'mode':self.p.cc.MODE,'candidate_id':self.config['candidate_id'],'session_id':self.config['session_id'],'private_root':self.config['private_root'],'roots':{r:self.config['roots'][r] for r in n.stage_context.ROOTS},'files':{r:files[r] for r in sorted(roles)},'host':self.host,'lineage':self.lineage,'invariants':self.p.cc.INVARIANTS,'stage':stage,'index':index,'stage_id':stage_id,'dependencies':{'context_pins_sha256':CONTEXT_SHA,'producer_pins_sha256':self.review['native_producer_pins_sha256'],'transport_pins_sha256':TRANSPORT_SHA,'transport_review_sha256':REVIEW_SHA}}
        path=self.candidate/'contexts'/(stage_id+'.json');identity=write_new(path,raw)
        ctx=n.stage_context.StageContext.read(path,identity['sha256'],self.config['roots']['context_package'])
        host_tools.verify_embedded(self.config)
        result=n.launch_stage.launch(ctx,self.config['native_environment']);ref=n.admission.receipt_ref(ctx)
        host_tools.verify_embedded(self.config)
        self.stages[(stage,index)]=(ctx,result,ref);return ctx,result,ref
    def output_pin(self,stage,name,index=None):
        ctx,env,_=self.stages[(stage,index)];require(name in env['output_files'],'required stage output missing')
        return file_pin(pin(ctx.output/name,env['output_files'][name]['sha256']))
    def gate(self,kind,keys):
        ctx=self.stages[keys[-1]][0];binding=dict(ctx.binding)
        if kind=='control':binding.pop('actual_fbx_sha256',None)
        value={'schema':'rust-duty-windows-native-gate/v1','kind':kind,'binding':binding,'stages':[self.stages[k][2] for k in keys]}
        path=self.candidate/'gates'/(kind+'.json');identity=write_new(path,value)
        self.p.native.admission.verify_gate(path,identity['sha256'],self.config['roots']['context_package']);self.files[kind+'_gate']=identity;return identity
    def conversion(self):
        self.native('control-export');self.files['control_fbx']=self.output_pin('control-export','animation.fbx')
        self.native('control-full');self.files['full_control']=self.output_pin('control-full','full-control.json')
        self.native('control-bounded');self.gate('control',[(n,None) for n in ('control-export','control-full','control-bounded')])
        self.native('export');self.files['actual_fbx']=self.output_pin('export','animation.fbx')
        self.native('source-focus');source=self.output_pin('source-focus','source-samples.json')
        self.native('focus-import',extra={'source_samples':source});self.gate('focus',[(n,None) for n in ('export','source-focus','focus-import')])
        self.native('rigid-frame1');self.files['rigid_frame1']=self.output_pin('rigid-frame1','rigid-frame1.json');self.native('rigid-focus')
        self.native('geometry');self.files['geometry']=self.output_pin('geometry','runtime/geometry-metadata.json')
        self.files['vrs']=self.output_pin('geometry','runtime/asset.vrs');self.files['vrm']=self.output_pin('geometry','runtime/asset.vrm')
        for i in range(12):self.native('block',i)
        self.gate('conversion',[('geometry',None)]+[('block',i) for i in range(12)])
    def assemble(self):
        c=self.candidate;cc=self.p.cc;root=c/'runtime';require(not root.exists(),'fresh runtime output required');root.mkdir()
        loader=module('pinned_assembler',Path(self.config['roots']['context_package'])/'pinned_assembler.py',{'candidate_context':cc})
        audited=Path(self.config['roots']['audited_source']);a=loader.load_assembler(audited/'onehand-runtime-20261016-r2/runtime-conversion-v2',audited/'onehand-runtime-20261016/importer-patch/tools')
        contract=a.StreamContract(source_sha256=self.files['generated_source']['sha256'],fbx_sha256=self.files['actual_fbx']['sha256'],canonical_sha256=cc.CANONICAL_SHA)
        require((contract.bone_count,contract.actor_count,contract.last_tick,contract.frame_bytes,contract.block_count)==(72,3,24320,3007,12),'full fixed assembler contract required')
        blocks=[Path(self.output_pin('block','block/receipt.json',i)['path']) for i in range(12)];metadata=Path(self.files['geometry']['path'])
        capacity(root,128*1024**2+sum(Path(self.files[k]['path']).stat().st_size for k in ('vrs','vrm')))
        result=a.assemble_stream(metadata,Path(self.files['vrs']['path']),Path(self.files['vrm']['path']),blocks,root/'asset.vra',contract=contract)
        report=c/'assembly-report.json';write_new(report,result)
        for role in ('vrs','vrm'):self.files[role]=materialize_companion(self.files[role]['path'],root/('asset.'+role))
        self.files['vra']=file_pin(root/'asset.vra');binding=self.stages[('geometry',None)][0].binding
        gate={'schema':'rust-duty-windows-runtime-assembly-inputs/v1','binding':binding,'conversion_gate':self.files['conversion_gate'],'assembly_report':record(report),'geometry':record(metadata),'blocks':[record(p) for p in blocks]}
        self.files['assembly_gate']=write_new(c/'gates'/'assembly.json',gate)
        manifest={'schema':'rust-duty-windows-runtime-manifest/v1','binding':binding,'assembly_gate_sha256':self.files['assembly_gate']['sha256'],'files':{k:self.files[k] for k in ('vra','vrs','vrm')},'timing_policy':{'kind':'explicit-rational-resampling','subdivisions':256,'switches':[],'samples':24321,'float32_collision_policy':'reject'},'runtime_parity_verified':False,'activation_authorized':False}
        self.files['manifest']=write_new(root/'manifest.json',manifest)
    def build(self):
        self.files['rust_build'],self.files['sampler']=build_rust.create_build(self.config,self.p.consumer,self.commands,self.candidate,self.host)
    def runtime_context(self):
        r=self.p.consumer.runtime_context
        raw={'schema':r.SCHEMA,'mode':self.p.cc.MODE,'candidate_id':self.config['candidate_id'],'session_id':self.config['session_id'],'private_root':self.config['private_root'],'roots':{k:self.config['roots'][k] for k in r.ROOTS},'files':{k:self.files[k] for k in sorted(r.FILES)},'host':self.host,'lineage':self.lineage,'invariants':self.p.cc.INVARIANTS,'dependencies':{'context_pins_sha256':CONTEXT_SHA,'consumer_pins_sha256':self.review['runtime_consumer_pins_sha256'],'producer_pins_sha256':self.review['native_producer_pins_sha256'],'transport_pins_sha256':TRANSPORT_SHA,'runtime_environment_sha256':digest(self.config['runtime_environment'])}}
        path=self.candidate/'contexts'/'runtime.json';fp=write_new(path,raw);self.runtime=r.RuntimeContext.read(path,fp['sha256'],self.config['roots']['context_package']);self.runtime.require_production()
        self.environment=write_new(self.candidate/'contexts'/'runtime-environment.json',self.config['runtime_environment'])
    def runtime_inputs(self,kind,index=None):
        keys={'initialize':{'source':('export',None),'rigid':('rigid-frame1',None)},'focus':{'source':('source-focus',None),'fbx':('focus-import',None),'rigid':('rigid-focus',None)},'chunk':{'source':('source-chunk',index),'fbx':('chunk-import',index),'rigid':('rigid-chunk',index)}}[kind]
        label=kind if index is None else f'{kind}-{index:03d}'
        return write_new(self.candidate/'contexts'/('runtime-inputs-'+label+'.json'),{'schema':'rust-duty-windows-runtime-inputs/v1','binding':self.runtime.runtime_binding,'kind':kind,'index':index,'stages':{k:self.stages[v][2] for k,v in keys.items()}})
    def consume(self,kind,index=None):
        ctx=self.runtime;args=['--context',str(ctx.path),'--context-sha256',sha(ctx.path),'--context-package',str(ctx.root('context_package')),'--environment',self.environment['path'],kind]
        if kind in ('initialize','focus','chunk'):
            inputs=self.runtime_inputs(kind,index);args+=['--inputs',inputs['path'],'--inputs-sha256',inputs['sha256']]
        if index is not None:args+=['--index',str(index)]
        label=kind if index is None else f'{kind}-{index:03d}'
        status=private_call(self.candidate/'controller-logs'/('runtime-'+label),lambda:self.p.consumer.consumer.main(args))
        require(status==0,'actual runtime '+kind+' failed; preserve private evidence')
    def prove(self):
        self.runtime_context();self.consume('loading');self.consume('initialize');self.consume('focus')
        for i in range(67):
            self.native('source-chunk',i);source=self.output_pin('source-chunk','source-samples.json',i)
            self.native('chunk-import',i,{'source_samples':source});self.native('rigid-chunk',i);self.consume('chunk',i)
        self.consume('aggregate')
        # Reconsume full aggregate; a file/passed flag is never the capture gate.
        ctx=self.runtime;m=self.p.consumer.pinned_math.load(ctx.root('audited_source'))
        result=self.p.consumer.consumer.aggregate(ctx,m,self.config['runtime_environment']);require(result['full_grid_parity'] is True and result['samples']==4240 and result['chunks']==67,'full-grid runtime completion missing')
        return {'schema':'rust-duty-onehand-private-capture-candidate/v1','binding':ctx.runtime_binding,'embedded_python_closure':self.config['embedded_python_closure'],'tool_hashes':{k:v['sha256'] for k,v in strict_json(self.files['host_binding']['path'])['tools'].items()},'rust_build':self.files['rust_build'],'runtime_aggregate':file_pin(ctx.output/'aggregate.json'),'runtime_context':file_pin(ctx.path),'runtime_assets':{k:self.files[k] for k in ('vra','vrs','vrm','manifest')},'capture_ready_private_candidate':True,'target_source_to_rust_proved':True,'approved_lineage_authored_admission':self.files['authored_admission'],'cross_platform_float64_equality_proved':False,'game_capture_binding_reviewed':False,'game_capture_performed':False,'artistic_approval':False,'activation_authorized':False,'raw_private_evidence_runner_local':True}

def run(config):
    review=reviewed_dependencies();p=load_packages(config,review);candidate,args,files=prepare(config,review,p)
    config['pins']={'context':CONTEXT_SHA,'producer':review['native_producer_pins_sha256']}
    host,host_pin,commands=host_tools.collect(config,p.adapter,p.cc,candidate,p.native.process_evidence.verify_completed_process);files['host_binding']=host_pin
    pipeline=Pipeline(config,review,p,candidate,args,files,host,commands)
    pipeline.replay();pipeline.conversion();pipeline.assemble();pipeline.build();result=pipeline.prove()
    write_new(candidate/'capture-candidate.json',result);return result

def summary(config,result=None,error=None):
    # Explicit hash-only public allowlist. Never dump an exception message,
    # arbitrary input JSON, native payload, environment values or captured logs.
    value={'schema':'rust-duty-onehand-windows-public-summary/v2','passed':result is not None,'private_raw_outputs_uploaded':False,'cross_platform_float64_equality_proved':False,'game_capture_performed':False,'game_capture_binding_reviewed':False,'runtime_asset_artifact_route':None,'candidate_retention':'private runner-local until teardown','source_projection_sha256':projection_binding.PROJECTION_SHA,'metadata_recipe_sha256':projection_binding.METADATA_RECIPE_SHA,'activation_authorized':False,'source_package_pins_sha256':SOURCE_SHA,'transport_pins_sha256':TRANSPORT_SHA,'controller_config_canonical_sha256':digest(config),'error_type':None if error is None else type(error).__name__,'error_sha256':None if error is None else hashlib.sha256(str(error).encode()).hexdigest(),'reproduction':['python','-I','-B','run_proof.py','--package-pins-sha256','<reviewed-package-sha256>','--config','<same-pinned-controller-config>','--config-sha256','<same-config-sha256>','run']}
    if result is not None:value.update(tool_hashes=result['tool_hashes'],rust_build_sha256=result['rust_build']['sha256'],runtime_aggregate_sha256=result['runtime_aggregate']['sha256'],runtime_context_sha256=result['runtime_context']['sha256'],runtime_assets={k:v['sha256'] for k,v in result['runtime_assets'].items()},target_source_sha256=result['binding']['generated_source_sha256'],approved_source_sha256=result['binding']['approved_source_sha256'],samples=4240,chunks=67,capture_ready_private_candidate=True)
    return value

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True);parser.add_argument('command',choices=['preflight','run'])
    args=parser.parse_args(argv);config=strict_json(pin(args.config,args.config_sha256));result=None;error=None
    try:
        if args.command=='preflight':review=reviewed_dependencies();p=load_packages(config,review);prepare(config,review,p);print(json.dumps({'preflight_passed':True,'native_execution_performed':False}));return 0
        result=run(config);return 0
    except Exception as exc:error=exc;print(json.dumps({'passed':False,'error_type':type(exc).__name__,'error_sha256':hashlib.sha256(str(exc).encode()).hexdigest()}));return 1
    finally:
        if args.command=='run':write_new(Path(config['evidence_root'])/'summary.json',summary(config,result,error),cap=128*1024)
