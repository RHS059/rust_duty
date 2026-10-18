"""CPU-only production verifier regression; no native launch or private asset.

External host/process provenance is synthetic. The actual _verify_stage path,
receipt parsing/binding, inventory checks and rigid payload/link validation run.
"""
import contextlib
import copy
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

import admission as a
import pinned_code as p
import stage_context as s

HERE = Path(__file__).absolute().parent

OLD_INVENTORY_LINE = "    require(type(files) is dict and 1<=len(files)<=150,'bounded output inventory')"
NEW_INVENTORY_BLOCK = "    # ctx.stage is already validated against the immutable context and exact\n    # receipt binding by _verify_stage. These two roles keep their complete\n    # rigid witnesses in the envelope payload, with no standalone output file.\n    payload_only=ctx.stage in ('rigid-focus','rigid-chunk')\n    require(type(files) is dict and (len(files)==0 if payload_only else 1<=len(files)<=150),'bounded output inventory')"

def original_admission_sha():
    raw=(HERE/'admission.py').read_bytes()
    assert raw.count(NEW_INVENTORY_BLOCK.encode())==1
    return hashlib.sha256(raw.replace(NEW_INVENTORY_BLOCK.encode(),OLD_INVENTORY_LINE.encode())).hexdigest()


class PayloadOnlyInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = HERE.parent/'windows-context-preparation-v3'
        if not root.is_dir(): root = HERE.parent/'context-v3'
        cls.cc = p.load_context(root)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).absolute()
        self.output = self.root/'native/rigid-focus'
        self.output.mkdir(parents=True)
        self.transport = self.root/'process/rigid-focus'
        self.transport.mkdir(parents=True)
        (self.transport/'terminal.json').write_text('{}\n')
        self.path = self.root/'contexts/rigid-focus.json'
        self.path.parent.mkdir()
        self.path.write_text('{}\n')
        self.tool = self.root/'tool.exe'
        self.tool.write_bytes(b'not executable; never launched')
        self.frames = [1., 1.1, 8., 8.1, 18., 18.1, 36., 36.1, 96.]
        self.ctx = N(stage='rigid-focus', index=None, path=self.path, output=self.output,
            transport_output=self.transport, candidate_root=self.root,
            context_sha256='c'*64, binding={'synthetic': 'binding'}, cc=self.cc,
            raw={'dependencies': {'producer_pins_sha256': p.file_sha(HERE/'PINS.json')}},
            root=lambda role: self.root, verify_files=lambda: None,
            host=N(runner_id='runner', run_id='run', build_sha256='b'*64,
                expected_host={'system':'Windows'}), owner_lock=self.root/'owner.lock',
            frames=lambda: self.frames)
        self.host = {'native_environment_sha256':'e'*64,
            'native_environment_keys':['SystemRoot'], 'tools':{
                name:{'path':str(self.tool), 'sha256':p.file_sha(self.tool)}
                for name in ('python','blender')}}
        self.env = {'schema':'rust-duty-windows-native-stage/v1', 'stage':self.ctx.stage,
            'index':None, 'context_sha256':self.ctx.context_sha256,
            'context_file_sha256':p.file_sha(self.path), 'binding':self.ctx.binding,
            'output_files':{}, 'payload':self.payload(), 'passed':True,
            'source_saved':False, 'rendered':False, 'cross_platform_float64_equality_proved':False,
            'runtime_equivalence_proved':False, 'artistic_approval':False, 'activation_authorized':False}

    def tearDown(self): self.tmp.cleanup()

    def payload(self):
        return {'samples':[{'source_frame':f,'actors':{}} for f in self.frames],
            'source_frames':list(self.frames),'actor_count':3,
            'full_float64_and_topology_bytes_compared':True,
            'source_bytes_unchanged':True,'in_memory_source_state_restored':True,
            'source_saved':False,'rendered':False}

    def verify(self):
        receipt=self.output/'receipt.json'
        receipt.write_text(json.dumps(self.env,separators=(',',':'))+'\n')
        @dataclasses.dataclass
        class Limits: deadline_seconds: float = 1800.
        with contextlib.ExitStack() as stack:
            # Do not fabricate Windows attestation. Only unrelated upstream
            # host/transport preconditions are stubbed for this CPU regression.
            for obj, name, value in ((a.StageContext,'read',self.ctx),
                (a,'host_build',self.host),(a,'verify_transport',N()),
                (a,'verify_completed_process',{'resources':{'synthetic':True}}),
                (a,'native_argv',['synthetic.exe']),(a,'process_limits',Limits()),
                (a,'validate_dependencies',None)):
                stack.enter_context(patch.object(obj,name,return_value=value))
            result=a._verify_stage(self.path,p.file_sha(self.path),self.root,
                p.file_sha(receipt),p.file_sha(self.transport/'terminal.json'))
        return result

    def set_stage(self, stage, index=None, frames=None):
        self.ctx.stage=stage; self.ctx.index=index
        self.env['stage']=stage; self.env['index']=index
        if frames is not None: self.frames=frames
        self.env['payload']=self.payload()

    def add_output(self,name='unexpected.bin',data=b'checked'):
        path=self.output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.env['output_files'][name]={'sha256':p.file_sha(path),'bytes':len(data)}

    def test_exact_hash_identifies_original_static_leaf(self):
        self.assertEqual(hashlib.sha256(b'bounded output inventory').hexdigest(),
            '45592e59a669386ffc00c05d739f18f18fc77387e982df7c926715fecf129422')

    def test_focus_payload_only_admitted_by_actual_verifier(self):
        self.assertEqual(self.verify()['output_files'],{})
        self.assertEqual({p.relative_to(self.output).as_posix() for p in self.output.rglob('*') if p.is_file()}, {'receipt.json'})

    def test_all_67_chunk_roles_continue_with_complete_payload(self):
        for i in range(67):
            count=64 if i<66 else 16
            self.set_stage('rigid-chunk',i,[float(j+1) for j in range(count)])
            got=self.verify()
            self.assertEqual(len(got['payload']['samples']),count)
            self.assertEqual(got['index'],i)

    def test_payload_roles_reject_even_valid_nonempty_inventory(self):
        for role,index in (('rigid-focus',None),('rigid-chunk',0)):
            self.set_stage(role,index);self.add_output()
            with self.subTest(role=role), self.assertRaisesRegex(ValueError,'bounded output inventory'): self.verify()

    def test_all_nonpayload_roles_and_unknown_roles_reject_empty(self):
        for stage in sorted(set(s.INPUTS)-{'rigid-focus','rigid-chunk'})+['unknown','rigid-focus-extra','prefix-rigid-chunk']:
            self.set_stage(stage,0 if stage in ('source-chunk','chunk-import','block') else None)
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError,'bounded output inventory'): self.verify()

    def test_receipt_stage_cannot_select_payload_exception(self):
        self.set_stage('rigid-frame1');self.env['stage']='rigid-focus'
        with self.assertRaises(ValueError):self.verify()

    def test_unlisted_disk_file_is_rejected_for_payload_only(self):
        for name in ('unexpected.bin','nested/receipt.json'):
            path=self.output/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'x')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'native output inventory/cap differs'):self.verify()
            path.unlink()

    def test_rigid_frame1_real_file_passes_but_tampering_fails(self):
        self.set_stage('rigid-frame1',frames=[1.]);self.add_output('rigid-frame1.json')
        self.verify()
        (self.output/'rigid-frame1.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'native output differs'):self.verify()

    def test_size_hash_and_path_tampering_are_rejected(self):
        self.set_stage('rigid-frame1',frames=[1.]);self.add_output('rigid-frame1.json')
        original=copy.deepcopy(self.env['output_files'])
        for field,value in (('bytes',False),('bytes',999),('sha256','f'*64)):
            self.env['output_files']=copy.deepcopy(original)
            self.env['output_files']['rigid-frame1.json'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.verify()
        for name in ('../rigid-frame1.json','nested\\rigid-frame1.json','/absolute.json'):
            self.env['output_files']={name:copy.deepcopy(original['rigid-frame1.json'])}
            with self.subTest(name=name),self.assertRaises(ValueError):self.verify()

    def test_payload_math_coverage_flags_are_still_required(self):
        for key,value in (('source_frames',[1.]),('actor_count',2),
            ('full_float64_and_topology_bytes_compared',False),('samples',[]),
            ('source_bytes_unchanged',False),('in_memory_source_state_restored',False)):
            self.env['payload']=self.payload();self.env['payload'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.verify()

    def test_other_stage_150_bound_unchanged(self):
        self.ctx.stage='other'
        for i in range(151):self.add_output('%03d.bin'%i,b'')
        with self.assertRaisesRegex(ValueError,'bounded output inventory'):
            a.verify_output_inventory(self.ctx,self.env)

class NativeEntryReceiptRoundtrip(unittest.TestCase):
    def test_actual_native_entry_inventory_and_controller_receipt_path(self):
        import native_entry as entry
        import native_stages
        import transport_binding
        context_root=HERE.parent/'windows-context-preparation-v3'
        if not context_root.is_dir():context_root=HERE.parent/'context-v3'
        cc=p.load_context(context_root)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).absolute();private=root/'private'
            candidate=private/'session/candidates/candidate';candidate.mkdir(parents=True)
            for role in ('rigid-focus','rigid-chunk'):
                index=66 if role=='rigid-chunk' else None
                stage_id=role if index is None else role+'-066'
                files={name:{'path':str(candidate/'inputs'/name),'sha256':'a'*64}
                    for name in s.COMMON|s.INPUTS[role]}
                for name in ('baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','transport_review','transport_smoke','transport_smoke_summary'):
                    files[name]['path']=str(root/'protected'/name)
                for name in ('reference_replay','reference_index','reference_equivalence'):
                    files[name]['path']=str(root/'reference'/name)
                for name,value in {'baseline':cc.BASE_SHA,'original_delta':cc.DELTA_SHA,'canonical':cc.CANONICAL_SHA,'source_grid':cc.GRID_SHA,'host_binding':'b'*64}.items():files[name]['sha256']=value
                roots={name:str(root/name) for name in s.ROOTS};roots['context_package']=str(context_root)
                raw={'schema':s.SCHEMA,'mode':cc.MODE,'candidate_id':'candidate','session_id':'session','private_root':str(private),
                    'roots':roots,'files':files,
                    'host':{'runner_id':'runner','run_id':'run','system':'Windows','release':'synthetic','version':'synthetic','machine':'AMD64','build_sha256':'b'*64},
                    'lineage':{'approved_source_sha256':cc.APPROVED_SHA,'source_package_pins_sha256':cc.SOURCE_PINS_SHA,'action_hashes':{name:'a'*64 for name in ('legacy','complete','metadata','auxiliary')},'static_state_sha256':'a'*64},
                    'invariants':copy.deepcopy(cc.INVARIANTS),'stage':role,'index':index,'stage_id':stage_id,
                    'dependencies':{'context_pins_sha256':p.CONTEXT_PINS_SHA,'producer_pins_sha256':p.file_sha(HERE/'PINS.json'),
                        'transport_pins_sha256':transport_binding.TRANSPORT_PINS_SHA,'transport_review_sha256':transport_binding.REVIEW_ACCEPTANCE_SHA}}
                path=candidate/'contexts'/(stage_id+'.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(raw)+'\n')
                ctx=s.StageContext.read(path,p.file_sha(path),context_root)
                frames=list(cc.FOCUS) if index is None else [float(i+1) for i in range(16)]
                # Full context validation and exact context/receipt hashes run.
                # Only unavailable source/Windows/Blender preconditions are
                # synthetic; no test claims numerical or native attestation.
                argv=['synthetic.exe','--context',str(path),'--context-sha256',p.file_sha(path)]
                ctx.owner_lock.write_bytes(b'synthetic owner')
                ctx.transport_output.mkdir(parents=True)
                (ctx.transport_output/'started.json').write_text(json.dumps({'pid':os.getpid(),'backend':'windows-job-list-overlapped-v2','command':argv,
                    'host_binding':{'context_sha256':ctx.context_sha256,'build_sha256':ctx.host.build_sha256}}))
                terminal=ctx.transport_output/'terminal.json';terminal.write_text('{}\n')
                tool=root/'tool.exe';tool.write_bytes(b'not executable')
                host={'native_environment_sha256':'e'*64,'native_environment_keys':['SystemRoot'],
                    'tools':{name:{'path':str(tool),'sha256':p.file_sha(tool)} for name in ('python','blender')}}
                payload={'source_bytes_unchanged':True,'in_memory_source_state_restored':True,'source_saved':False,'rendered':False,
                    'source_frames':frames,'samples':[{'source_frame':f,'actors':{}} for f in frames],
                    'actor_count':3,'full_float64_and_topology_bytes_compared':True}
                @dataclasses.dataclass
                class Limits: deadline_seconds:float=1800.
                with contextlib.ExitStack() as stack:
                    for obj,name,value in ((s.StageContext,'verify_files',None),(entry,'host_build',host),(entry,'verify_transport',N()),
                        (entry,'native_argv',argv),(entry,'validate_dependencies',None),(native_stages,'perform',payload),
                        (a,'host_build',host),(a,'verify_transport',N()),(a,'verify_completed_process',{'resources':{}}),
                        (a,'native_argv',argv),(a,'process_limits',Limits()),(a,'validate_dependencies',None)):
                        stack.enter_context(patch.object(obj,name,return_value=value))
                    stack.enter_context(patch.object(s.StageContext,'frames',return_value=frames))
                    stack.enter_context(patch.object(sys,'argv',['native_entry.py','--factory-startup','--disable-autoexec']))
                    entry.main(['--context',str(path),'--context-sha256',p.file_sha(path),'--context-package',str(context_root),
                        '--producer-pins-sha256',p.file_sha(HERE/'PINS.json')])
                    receipt=ctx.output/'receipt.json';before=receipt.read_bytes()
                    got=a.verify_stage(path,p.file_sha(path),context_root,p.file_sha(receipt),p.file_sha(terminal))
                    self.assertEqual(got['output_files'],{});self.assertEqual(got['payload'],payload)
                    self.assertEqual(receipt.read_bytes(),before)
                    self.assertEqual(set(x.name for x in ctx.output.iterdir()),{'receipt.json'})
                    with self.assertRaisesRegex(ValueError,'stage context file pin differs'):
                        a.verify_stage(path,'f'*64,context_root,p.file_sha(receipt),p.file_sha(terminal))
                    with self.assertRaisesRegex(ValueError,'native envelope pin differs'):
                        a.verify_stage(path,p.file_sha(path),context_root,'f'*64,p.file_sha(terminal))

if __name__=='__main__':unittest.main(verbosity=2)
