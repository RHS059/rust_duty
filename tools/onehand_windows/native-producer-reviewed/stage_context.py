"""Immutable early-native stages. Generated source and approved lineage differ.

A stage snapshot pins only existing read-only input roles; outputs are fresh fixed
paths. Later stages refer to earlier snapshots and retained process evidence,
never rewrite predecessor receipts to a later context hash.
"""
from dataclasses import dataclass
import hashlib,json,math,os,shutil,sys
from pathlib import Path
from pinned_code import HERE,CONTEXT_PINS_SHA,load_context,require,file_sha,verify_originals
SCHEMA='rust-duty-windows-native-stage-context/v1'
COMMON={'generated_source','target_replay','authored_admission','host_binding','baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','transport_review','transport_smoke','transport_smoke_summary'}
INPUTS={
 'export':set(), 'control-export':set(), 'source-focus':{'actual_fbx'}, 'source-chunk':{'actual_fbx','control_gate','focus_gate'},
 'rigid-frame1':{'actual_fbx','control_gate','focus_gate'},
 'rigid-chunk':{'actual_fbx','control_gate','focus_gate','rigid_frame1'},
 'rigid-focus':{'actual_fbx','control_gate','focus_gate','rigid_frame1'},
 'control-full':{'control_fbx'}, 'control-bounded':{'control_fbx','full_control'},
 'focus-import':{'actual_fbx','control_gate','source_samples'},
 'chunk-import':{'actual_fbx','control_gate','focus_gate','source_samples'},
 'geometry':{'actual_fbx','control_gate','focus_gate'},
 'block':{'actual_fbx','control_gate','focus_gate','geometry','vrs','vrm'},
}
ROOTS={'audited_source','source_package','reference','blender_bundle','context_package','process_adapter'}
SOURCE_STAGES={'export','control-export','source-focus','source-chunk','rigid-frame1','rigid-chunk','rigid-focus'}
GIB=1024**3;MIB=1024**2

@dataclass(frozen=True)
class StageContext:
    raw:dict
    cc:object
    path:Path
    @classmethod
    def read(cls,path,expected_sha,context_package):
        cc=load_context(context_package);p=cc.ordinary(path,existing=True)
        cc.sha(expected_sha);require(file_sha(p)==expected_sha,'stage context file pin differs')
        value=cc.strict_json(p);out=cls(value,cc,p);out.validate()
        require(out.root('context_package')==cc.ordinary(context_package),'explicit context package root differs')
        return out
    def validate(self, *, fresh=False):
        c=self.cc;d=self.raw
        c.exact_keys(d,('schema','mode','candidate_id','session_id','private_root','roots','files','host','lineage','invariants','stage','index','stage_id','dependencies'),'stage context')
        c.exact(d['schema'],SCHEMA,'stage schema');c.exact(d['mode'],c.MODE,'mode')
        require(d['stage'] in INPUTS,'unknown native stage')
        c.identifier(d['candidate_id'],'candidate');c.identifier(d['session_id'],'session');c.identifier(d['stage_id'],'stage')
        c.exact_keys(d['roots'],ROOTS,'roots');c.exact_keys(d['files'],COMMON|INPUTS[self.stage],'stage roles')
        c.exact_keys(d['invariants'],c.INVARIANTS,'invariants')
        for k,v in c.INVARIANTS.items():c.exact(d['invariants'][k],v,k)
        c.exact_keys(d['lineage'],('approved_source_sha256','source_package_pins_sha256','action_hashes','static_state_sha256'),'lineage')
        c.exact(d['lineage']['approved_source_sha256'],c.APPROVED_SHA,'approved lineage')
        c.exact(d['lineage']['source_package_pins_sha256'],c.SOURCE_PINS_SHA,'authored source closure')
        c.exact_keys(d['lineage']['action_hashes'],('legacy','complete','metadata','auxiliary'),'Action hashes')
        for v in d['lineage']['action_hashes'].values():c.sha(v)
        c.sha(d['lineage']['static_state_sha256'])
        c.HostBuildBinding.parse(d['host'])
        paths=[self.pin(r).path for r in d['files']];roots=[self.root(r) for r in ROOTS]
        require(len({str(p).casefold() for p in paths})==len(paths),'role aliases')
        identities=[(p.stat().st_dev,p.stat().st_ino) for p in paths if p.exists()]
        require(len(set(identities))==len(identities),'hardlinked role aliases')
        private=c.ordinary(d['private_root']);candidate=self.candidate_root
        require(len({str(p).casefold() for p in roots})==len(roots),'root aliases')
        for r in roots:require(not r.is_relative_to(private) and not private.is_relative_to(r),'protected/output roots overlap')
        protected={'baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','transport_review','transport_smoke','transport_smoke_summary'}
        for role in d['files']:
            p=self.pin(role).path
            require(not p.is_relative_to(private) if role in protected else p.is_relative_to(candidate),'wrong input role root: '+role)
        for role in ('reference_replay','reference_index','reference_equivalence'):
            require(self.pin(role).path.is_relative_to(self.root('reference')),'reference escapes hash-only root')
        for r,v in {'baseline':c.BASE_SHA,'original_delta':c.DELTA_SHA,'canonical':c.CANONICAL_SHA,'source_grid':c.GRID_SHA}.items():c.exact(self.pin(r).sha256,v,r)
        require(self.pin('generated_source').sha256 not in (c.APPROVED_SHA,c.BASE_SHA),'generated source lineage laundering')
        c.exact(self.pin('host_binding').sha256,self.host.build_sha256,'host manifest')
        if self.stage in ('source-chunk','rigid-chunk','chunk-import'):require(type(self.index) is int and 0<=self.index<67,'chunk 0..66 required')
        elif self.stage=='block':require(type(self.index) is int and 0<=self.index<12,'block 0..11 required')
        else:require(self.index is None,'stage takes no index')
        require(self.path.is_relative_to(candidate/'contexts'),'context outside fixed candidate contexts')
        for p in (self.output,self.transport_output):
            c.ordinary(p)
            if fresh:require(not p.exists(),'fresh bounded output required')
            for input_path in paths:require(not input_path.is_relative_to(p) and not p.is_relative_to(input_path),'output aliases input')
        c.exact_keys(d['dependencies'],('context_pins_sha256','producer_pins_sha256','transport_pins_sha256','transport_review_sha256'),'dependencies')
        c.exact(d['dependencies']['context_pins_sha256'],CONTEXT_PINS_SHA,'context freeze')
        for value in d['dependencies'].values():c.sha(value)
        return self
    @property
    def stage(self):return self.raw['stage']
    @property
    def index(self):return self.raw['index']
    @property
    def candidate_id(self):return self.raw['candidate_id']
    @property
    def session_id(self):return self.raw['session_id']
    @property
    def host(self):return self.cc.HostBuildBinding.parse(self.raw['host'])
    @property
    def action_hashes(self):return tuple(sorted(self.raw['lineage']['action_hashes'].items()))
    @property
    def static_state_sha256(self):return self.raw['lineage']['static_state_sha256']
    @property
    def candidate_root(self):return self.cc.ordinary(self.raw['private_root'])/self.session_id/'candidates'/self.candidate_id
    @property
    def owner_lock(self):return self.cc.ordinary(self.raw['private_root'])/self.session_id/'native-owner.lock'
    @property
    def output(self):return self.candidate_root/'native'/self.raw['stage_id']
    @property
    def transport_output(self):return self.candidate_root/'process'/self.raw['stage_id']
    @property
    def context_sha256(self):return self.cc.digest(self.raw)
    def root(self,role):return self.cc.ordinary(self.raw['roots'][role])
    def pin(self,role):return self.cc.FilePin.parse(role,self.raw['files'][role])
    def record(self):return self.raw
    @property
    def binding(self):
        d={'mode':self.cc.MODE,'candidate_id':self.candidate_id,'session_id':self.session_id,
           'runner_id':self.host.runner_id,'run_id':self.host.run_id,'approved_source_sha256':self.cc.APPROVED_SHA,
           'generated_source_sha256':self.pin('generated_source').sha256,'canonical_sha256':self.cc.CANONICAL_SHA,
           'source_grid_sha256':self.cc.GRID_SHA,'authored_admission_sha256':self.pin('authored_admission').sha256,'host_build_sha256':self.host.build_sha256}
        if 'actual_fbx' in self.raw['files']:d['actual_fbx_sha256']=self.pin('actual_fbx').sha256
        return d
    def verify_files(self):
        for role in self.raw['files']:self.pin(role).verify()
        require(file_sha(self.root('source_package')/'PINS.json')==self.cc.SOURCE_PINS_SHA,'source package freeze differs')
        for n,v in self.cc.strict_json(self.root('source_package')/'PINS.json').items():
            require(Path(n).name==n and file_sha(self.root('source_package')/n)==v,'source package closure differs')
        reference=self.cc.strict_json(self.pin('reference_index').path)
        self.cc.exact_keys(reference,(f'{kind}-{i:03}.json' for i in range(17) for kind in ('approved','regenerated')),'34 reference witnesses')
        for n,v in reference.items():require(file_sha(self.root('reference')/n)==v,'reference witness differs')
        self.cc.ProofContext.validate_authored_receipt(self,self.cc.strict_json(self.pin('authored_admission').path))
        grid=self.cc.strict_json(self.pin('source_grid').path)
        require(len(grid)==4240 and grid==sorted(set(grid)) and grid[0]==1 and grid[-1]==96,'original ordered grid required')
        verify_originals(self.root('audited_source'));return self
    def frames(self):
        if self.stage in ('source-focus','focus-import','control-full','control-bounded','rigid-focus'):return list(self.cc.FOCUS)
        if self.stage in ('source-chunk','rigid-chunk','chunk-import'):
            return self.cc.strict_json(self.pin('source_grid').verify())[self.index*64:(self.index+1)*64]
        if self.stage=='block':
            lo=self.index*2048;hi=min(lo+2048,24320);return [1+i/256 for i in range(lo,hi+1)]
        return [1.,96.] if self.stage in ('export','control-export') else [1.]

def capacity(path,additional):
    p=Path(path)
    while not p.exists():p=p.parent
    require(shutil.disk_usage(p).free>=GIB+additional,'1 GiB disk floor plus stage reserve required')

def write_new(path,value,cap=32*MIB):
    raw=(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode()
    require(len(raw)<=cap,'bounded JSON output exceeded');capacity(Path(path).parent,len(raw))
    with Path(path).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
