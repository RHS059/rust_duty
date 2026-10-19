"""Distinct nine-time actual-Rust focus, including four between-key samples."""
from pathlib import Path
from onehand_r2_common import *
import verify_onehand_r2 as v
import admit_candidate as admission
import window_admission as window

FOCUS=WORK/'focus-output-v2'
RIGID_RECIPE=WORK/'native-focus-rigid-v2'
RIGID_PROCESS=WORK/'logs/focus-rigid-v2/process-receipt.json'


def result_path():return safe_output('runtime-parity/focused-runtime.json')


def rigid_witness(session):
    path=FOCUS/'rigid-samples.json';value=read(path);grid_sha=sha(WORK/'native-dense/focus-times.json')
    method='exact_float64_and_topology_bytes_vs_verified_frame1'
    for key,expected in {'schema':'rust-duty-private-onehand-rigid-focus/v1','source_sha256':SOURCE_SHA,
                         'rig_action':ACTION,'rig_action_fingerprint':ACTION_SHA,'sample_grid_sha256':grid_sha,
                         'independent_grid_sha256':GRID_SHA,'chunk_index':None,'source_frames':FOCUS_FRAMES,
                         'passed':True,'verification_method':method,'frame1_witness_sha256':FRAME1_SHA}.items():
        exact(value.get(key),expected,'independent focus rigid '+key)
    baseline,geometry=v.rigid_frame1(session['files']['rigid_frame1']['path'],session['initial_source'])
    samples=value.get('samples',[]);require(len(samples)==9,'rigid focused sample count differs')
    for frame,row in zip(FOCUS_FRAMES,samples):
        require(row.get('source_frame')==frame and set(row.get('actors',{}))==set(ACTORS),'rigid focus time/actor coverage differs')
        for name,actor in row['actors'].items():
            require(actor.get('geometry_sha256')==baseline['actors'][name]['geometry_sha256'] and actor.get('hide_render') is False,'rigid focus full local geometry differs')
    receipt_path=path.with_name('rigid-samples.receipt.json');receipt=read(receipt_path)
    for key,expected in {'schema':'rust-duty-onehand-rigid-process/v1','mode':'focus','chunk_index':None,
                         'source_sha256':SOURCE_SHA,'rig_action_fingerprint':ACTION_SHA,'sample_grid_sha256':grid_sha,
                         'independent_grid_sha256':GRID_SHA,'output_sha256':sha(path),'output_bytes':path.stat().st_size,
                         'samples':9,'source_bytes_unchanged':True,'in_memory_source_state_restored':True,
                         'source_saved':False,'rendered':False,'passed':True,'verification_method':method,
                         'frame1_witness_sha256':FRAME1_SHA,'recipe_pins_sha256':sha(RIGID_RECIPE/'pins.json')}.items():
        exact(receipt.get(key),expected,'focused rigid receipt '+key)
    producer=admission.pinned_producer(RIGID_RECIPE/'pins.json',receipt['recipe_pins_sha256'])
    process=v.process_record(RIGID_PROCESS,blender=True)
    record=process['record'];window.validate_resource_process(record)
    require(record.get('source_sha256')==SOURCE_SHA,'focused rigid native source differs')
    expected=[record['command'][0],'--background','--factory-startup','--disable-autoexec','--threads','1',
              session['files']['source']['path'],'--python-exit-code','1','--python',str(RIGID_RECIPE/'sample_rigid.py'),'--',
              'focus','--output',str(path),'--frame1-witness',str(ORIGINAL_WORK/'rigid-frame1-v1.json'),'--frame1-sha256',FRAME1_SHA]
    require(record['command']==expected and record.get('blender_sha256')==session['processes']['export']['record']['blender_sha256'],'focused rigid native command/binary differs')
    require(record.get('recipe_pins_sha256')==sha(RIGID_RECIPE/'pins.json') and record.get('owner_lock')==str(ROOT/'native-owner.lock'),'focused rigid native recipe/owner differs')
    pin(RIGID_PROCESS.parent/'run.log',record['stdout_sha256'])
    return geometry,{'rigid_witness':v.file_record(path),'rigid_receipt':v.file_record(receipt_path),
                     **{'rigid_producer/'+name:rec for name,rec in producer.items()}},process


def validate(session,*,check_files=True):
    path=result_path();value=read(path)
    for key,expected in {'schema':'rust-duty-onehand-focused-runtime/v2',**candidate_identity(),'passed':True,
                         'session_sha256':sha(HERE/'session.json'),'correspondence_sha256':session['correspondence_sha256'],
                         'source_frames':FOCUS_FRAMES,'samples':9,'off_key_source_frames':FOCUS_FRAMES[1::2],
                         'runtime_pins':{name:session['files'][name]['sha256'] for name in ('asset.vra','asset.vrs','asset.vrm','manifest','sampler','canonical')},
                         'thresholds':THRESHOLDS,'distinct_focus_only':True,'full_grid_parity':False,'runtime_activated':False}.items():
        exact(value.get(key),expected,'actual Rust focus '+key)
    records=value.get('records',[])
    require([r.get('source_frame') for r in records]==FOCUS_FRAMES,'runtime focus exact ordering differs')
    require([r.get('time_seconds') for r in records]==[(f-1)/60 for f in FOCUS_FRAMES],'runtime focus requested clock differs')
    require(v.summarize(records)==value.get('summary'),'runtime focus measured summary differs')
    require(value['summary']['skin_vertex_observations']==92106 and value['summary']['canonical_bone_observations']==648,'runtime focus complete geometry counts differ')
    process=value.get('process',{});window.validate_resource_process(process)
    require(process.get('command')==[session['files']['sampler']['path'],session['files']['asset.vra']['path'],ACTION,*[repr((f-1)/60) for f in FOCUS_FRAMES],'--clamp']
            and process.get('sampler_sha256')==SAMPLER_SHA and process.get('rows')==9,'actual Rust focused command/coverage differs')
    window.sha_string(process.get('stdout_sha256'))
    if check_files:
        for record in value['evidence'].values():v.check_record(record)
        _,_,native=rigid_witness(session)
        require(native==value.get('rigid_process'),'independent focused rigid process changed')
        require(value.get('source_fbx_sha256')==sha(FOCUS/'fresh-import-parity.json'),'focus FBX receipt changed')
    return value


def run(args):
    session=v.load_session(args.session);require(Path(args.session).resolve()==HERE/'session.json','focused session path differs')
    path=result_path();failure=safe_output('runtime-parity/focused-runtime.failed.json');process={}
    require(not path.exists() and not failure.exists(),'preserve previous actual Rust focus attempt')
    try:
        witness,invariants=v.source_index(FOCUS/'source-samples.json',FOCUS_FRAMES,session['invariants_sha256'])
        admission.validate_focus(read(FOCUS/'fresh-import-parity.json'),session['files']['fbx']['sha256'],sha(WORK/'native-dense/focus-times.json'),sha(FOCUS/'source-samples.json'),sha(FOCUS/'export-receipt.json'))
        geometry,evidence,rigid_process=rigid_witness(session)
        files=session['files'];pack,bones,counts,rigid=v.load_runtime(Path(files['asset.vra']['path']),Path(files['canonical']['path']),files['fbx']['sha256'])
        checker=v.Checker(pack,bones,counts,rigid,invariants,session['initial_source'],geometry,session['correspondence'])
        records=[]
        command=[files['sampler']['path'],files['asset.vra']['path'],ACTION,*[repr((f-1)/60) for f in FOCUS_FRAMES],'--clamp']
        with v.probe(command,process) as rows:
            for descriptor in witness['frames'].values():
                pose=next(rows,None);require(pose is not None,'Rust focus sample missing')
                source,skin=v.load_row(FOCUS,descriptor,invariants['source_rest_world'])
                records.append(checker.check(pose,source,skin))
            require(next(rows,None) is None,'Rust focus extra sample')
        window.validate_resource_process(process)
        for name in ('source-samples.json','export-receipt.json','fresh-import-parity.json'):
            evidence[name]=v.file_record(FOCUS/name)
        for descriptor in witness['frames'].values():
            for kind in ('row','skin'):
                relative=descriptor[kind+'_path'];evidence[relative]=v.file_record(bounded(FOCUS,relative))
        value={'schema':'rust-duty-onehand-focused-runtime/v2',**candidate_identity(),'passed':True,
               'session_sha256':sha(args.session),'correspondence_sha256':session['correspondence_sha256'],
               'source_frames':FOCUS_FRAMES,'samples':9,'off_key_source_frames':FOCUS_FRAMES[1::2],
               'runtime_pins':{name:files[name]['sha256'] for name in ('asset.vra','asset.vrs','asset.vrm','manifest','sampler','canonical')},
               'thresholds':THRESHOLDS,'records':records,'summary':v.summarize(records),'process':process,'evidence':evidence,
               'rigid_process':rigid_process,'source_fbx_sha256':sha(FOCUS/'fresh-import-parity.json'),
               'distinct_focus_only':True,'full_grid_parity':False,'runtime_activated':False}
        v.load_session(args.session);write_new(path,value);validate(session)
        return {'passed':True,'focused_runtime':str(path),'sha256':sha(path),'samples':9,'off_key_samples':4,'full_grid_parity':False}
    except BaseException as exc:
        write_new(failure,{'passed':False,**candidate_identity(),'process':process,'error':type(exc).__name__+': '+str(exc)})
        raise
