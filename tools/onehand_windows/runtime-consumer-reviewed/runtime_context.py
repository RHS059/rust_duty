"""Strict target-runtime snapshot. Schema validation is never production admission."""
from __future__ import annotations
from dataclasses import dataclass
import os,platform,re,shutil,struct,sys
from pathlib import Path
import pinned_math as p
SCHEMA='rust-duty-windows-runtime-context/v1'
FILES={'generated_source','target_replay','authored_admission','host_binding','baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','actual_fbx','vra','vrs','vrm','manifest','assembly_gate','rust_build','sampler','transport_review','transport_smoke','transport_smoke_summary'}
ROOTS={'audited_source','context_package','native_producer','process_adapter','source_package','reference','rust_source'}
SAMPLER_SOURCE='82123dbb8be6db54a3780a2b18079a809738cd2559f89de7dcee0aac1d31e22b'
OLD_ELF='8f8de71a2fca6f36469dd520d3b1a14c43f0839f91c910faa4974e3a91916fcb'
GIB=1024**3
# Source revisions must update these only after independent review. A caller's
# self-written "approved" receipt or an alternate CLI flag cannot admit code.
REVIEWED_TRANSPORT_PINS_SHA='d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751'
TRANSPORT_REVIEW_SHA='820c10f716aadfb3ee9f7e3e3c8e176b446df0568f4196dce4fd0b7c08cf6527'
REVIEWED_PRODUCER_PINS_SHA='cfc96363113616ce8b2450fe172790270f32538ed3c0660ae8a4d848148e4794'
# Independent pair review accepts producer v3 corrections; its sole consumer
# blocker B1 is corrected by this revision and still needs independent re-review.
PRODUCER_REVIEW_PINS_SHA='d704d46e75d7f28865bde42aea1ad1ea75a84089600b1a40053d8ae064747b79'
PRODUCER_REVIEW_DOCUMENT_SHA='163f4d1f7e17ae4cb7f0ccd4bf5e2babe855368a1bc9090c4f52a4e18a1e74f4'

def capacity(path,additional=0):
    path=Path(path)
    while not path.exists():path=path.parent
    p.require(shutil.disk_usage(path).free>=GIB+additional,'1 GiB disk floor plus bounded output reserve required')

def pe_x64(path):
    with Path(path).open('rb') as f:
        head=f.read(64);p.require(len(head)==64 and head[:2]==b'MZ','actual PE binary required')
        offset=struct.unpack_from('<I',head,60)[0];p.require(64<=offset<=16*1024**2,'PE header offset invalid');f.seek(offset);h=f.read(26)
    p.require(len(h)==26 and h[:4]==b'PE\0\0' and struct.unpack_from('<H',h,4)[0]==0x8664,'x64 PE required')
    flags=struct.unpack_from('<H',h,22)[0]
    p.require(flags&2 and not flags&0x2000 and struct.unpack_from('<H',h,24)[0]==0x20b,'PE32+ executable required')
    return {'machine':'AMD64','format':'PE32+','sha256':p.sha(path)}

def record(path):
    path=Path(path);return {'path':str(path),'sha256':p.sha(path),'bytes':path.stat().st_size}

def check_record(value,cc,root=None):
    cc.exact_keys(value,('path','sha256','bytes'),'file record');path=cc.ordinary(value['path'],existing=True)
    cc.sha(value['sha256']);p.require(type(value['bytes']) is int and value['bytes']>=0,'invalid bytes')
    if root is not None:p.require(path.is_relative_to(root),'file outside candidate')
    p.require(path.is_file() and path.stat().st_size==value['bytes'],'file size differs');p.pin(path,value['sha256']);return path

def inventory(root,cc):
    root=cc.ordinary(root,existing=True);out={}
    for base,dirs,names in os.walk(root,followlinks=False):
        # No basename or VCS/build-output pruning: even nested target/.git
        # may be compiler input. Build outputs must use a separate target root.
        dirs[:]=sorted(dirs)
        for d in dirs:cc.ordinary(Path(base)/d,existing=True)
        for n in sorted(names):
            f=cc.ordinary(Path(base)/n,existing=True);p.require(f.is_file(),'source closure non-file')
            out[f.relative_to(root).as_posix()]=cc.file_sha(f)
    p.require(out,'empty source closure');return out

@dataclass(frozen=True)
class RuntimeContext:
    raw:dict
    cc:object
    path:Path
    @classmethod
    def read(cls,path,expected_sha,context_package):
        cc=p.context_module(context_package);path=cc.ordinary(path,existing=True);cc.sha(expected_sha);p.pin(path,expected_sha)
        result=cls(cc.strict_json(path),cc,path);result.validate();return result
    def validate(self):
        c=self.cc;d=self.raw
        c.exact_keys(d,('schema','mode','candidate_id','session_id','private_root','roots','files','host','lineage','invariants','dependencies'),'runtime context')
        c.exact(d['schema'],SCHEMA,'schema');c.exact(d['mode'],c.MODE,'mode')
        for key in ('candidate_id','session_id'):c.identifier(d[key],key)
        c.exact_keys(d['roots'],ROOTS,'roots');c.exact_keys(d['files'],FILES,'roles')
        c.exact_keys(d['invariants'],c.INVARIANTS,'invariants')
        for k,v in c.INVARIANTS.items():c.exact(d['invariants'][k],v,k)
        c.exact_keys(d['lineage'],('approved_source_sha256','source_package_pins_sha256','action_hashes','static_state_sha256'),'lineage')
        c.exact(d['lineage']['approved_source_sha256'],c.APPROVED_SHA,'approved lineage')
        c.exact(d['lineage']['source_package_pins_sha256'],c.SOURCE_PINS_SHA,'source closure')
        c.exact_keys(d['lineage']['action_hashes'],('legacy','complete','metadata','auxiliary'),'Action hashes')
        for v in d['lineage']['action_hashes'].values():c.sha(v)
        c.sha(d['lineage']['static_state_sha256']);c.HostBuildBinding.parse(d['host'])
        c.exact_keys(d['dependencies'],('context_pins_sha256','consumer_pins_sha256','producer_pins_sha256','transport_pins_sha256','runtime_environment_sha256'),'dependencies')
        c.exact(d['dependencies']['context_pins_sha256'],p.CONTEXT_PINS_SHA,'context freeze')
        for v in d['dependencies'].values():c.sha(v)
        private=c.ordinary(d['private_root']);paths=[self.pin(k).path for k in FILES]
        p.require(len({str(x).casefold() for x in paths})==len(paths),'file roles alias')
        actual=[(x.stat().st_dev,x.stat().st_ino) for x in paths if x.exists()]
        p.require(len(actual)==len(set(actual)),'hardlinked role aliases')
        protected={'baseline','original_delta','canonical','source_grid','reference_replay','reference_index','reference_equivalence','sampler','transport_review','transport_smoke','transport_smoke_summary'}
        roots=[self.root(k) for k in ROOTS];p.require(len({str(x).casefold() for x in roots})==len(roots),'root aliases')
        for root in roots:p.require(not root.is_relative_to(private) and not private.is_relative_to(root),'protected root/private overlap')
        for role in FILES:
            f=self.pin(role).path;p.require(not f.is_relative_to(private) if role in protected else f.is_relative_to(self.candidate_root),'foreign candidate/session role: '+role)
        for role in ('reference_replay','reference_index','reference_equivalence'):p.require(self.pin(role).path.is_relative_to(self.root('reference')),'reference root differs')
        for role,value in {'baseline':c.BASE_SHA,'original_delta':c.DELTA_SHA,'canonical':c.CANONICAL_SHA,'source_grid':c.GRID_SHA}.items():c.exact(self.pin(role).sha256,value,role)
        p.require(self.pin('generated_source').sha256 not in (c.APPROVED_SHA,c.BASE_SHA),'generated identity laundering')
        p.require(self.pin('sampler').sha256!=OLD_ELF,'Linux ELF sampler identity forbidden')
        c.exact(self.pin('host_binding').sha256,self.host.build_sha256,'native host manifest')
        for role,name in [('vra','asset.vra'),('vrs','asset.vrs'),('vrm','asset.vrm'),('manifest','manifest.json')]:
            p.require(self.pin(role).path==self.candidate_root/'runtime'/name,'actual companion layout differs')
        p.require(self.path.is_relative_to(self.candidate_root/'contexts'),'runtime context outside candidate contexts')
        return self
    @property
    def host(self):return self.cc.HostBuildBinding.parse(self.raw['host'])
    @property
    def candidate_root(self):return self.cc.ordinary(self.raw['private_root'])/self.raw['session_id']/'candidates'/self.raw['candidate_id']
    @property
    def owner_lock(self):return self.cc.ordinary(self.raw['private_root'])/self.raw['session_id']/'native-owner.lock'
    @property
    def output(self):return self.candidate_root/'runtime-proof'
    @property
    def context_sha256(self):return p.digest(self.raw)
    @property
    def action_hashes(self):return tuple(sorted(self.raw['lineage']['action_hashes'].items()))
    @property
    def static_state_sha256(self):return self.raw['lineage']['static_state_sha256']
    def pin(self,role):return self.cc.FilePin.parse(role,self.raw['files'][role])
    def root(self,role):return self.cc.ordinary(self.raw['roots'][role])
    @property
    def binding(self):
        return {'mode':self.cc.MODE,'candidate_id':self.raw['candidate_id'],'session_id':self.raw['session_id'],'runner_id':self.host.runner_id,'run_id':self.host.run_id,'approved_source_sha256':self.cc.APPROVED_SHA,'generated_source_sha256':self.pin('generated_source').sha256,'actual_fbx_sha256':self.pin('actual_fbx').sha256,'canonical_sha256':self.cc.CANONICAL_SHA,'source_grid_sha256':self.cc.GRID_SHA,'authored_admission_sha256':self.pin('authored_admission').sha256,'host_build_sha256':self.host.build_sha256}
    @property
    def runtime_binding(self):
        return {**self.binding,'runtime_context_sha256':self.context_sha256,'rust_build_sha256':self.pin('rust_build').sha256,'sampler_sha256':self.pin('sampler').sha256,'runtime_assets':{k:self.pin(k).sha256 for k in ('vra','vrs','vrm','manifest')},'consumer_pins_sha256':self.raw['dependencies']['consumer_pins_sha256']}
    def grid(self):
        values=self.cc.strict_json(self.pin('source_grid').verify());p.require(type(values) is list and len(values)==4240 and all(type(v) is float and __import__('math').isfinite(v) for v in values),'exact float4240 grid')
        p.require(values==sorted(set(values)) and values[0]==1 and values[-1]==96,'grid ordering/endpoints');return values
    def verify_files(self):
        self.validate()
        for role in FILES:self.pin(role).verify()
        self.grid();self.cc.ProofContext.validate_authored_receipt(self,self.cc.strict_json(self.pin('authored_admission').path))
        p.pin(self.root('source_package')/'PINS.json',self.cc.SOURCE_PINS_SHA)
        for n,v in self.cc.strict_json(self.root('source_package')/'PINS.json').items():
            p.require(Path(n).name==n,'unsafe source package pin');p.pin(self.root('source_package')/n,v)
        index=self.cc.strict_json(self.pin('reference_index').path)
        self.cc.exact_keys(index,(f'{k}-{i:03}.json' for i in range(17) for k in ('approved','regenerated')),'reference34')
        for n,v in index.items():p.pin(self.root('reference')/n,v)
        return self
    def require_production(self):
        # Every actual role, host, build and candidate remains mandatory.
        # Source dependency acceptance is not itself actual runtime proof.
        p.require(REVIEWED_TRANSPORT_PINS_SHA is not None,'reviewed v2 transport pin absent; source-only consumer cannot admit production')
        p.require(REVIEWED_PRODUCER_PINS_SHA is not None,'reviewed producer/assembler admission pins absent')
        for field,want,root in [('transport_pins_sha256',REVIEWED_TRANSPORT_PINS_SHA,'process_adapter'),('producer_pins_sha256',REVIEWED_PRODUCER_PINS_SHA,'native_producer')]:
            self.cc.exact(self.raw['dependencies'][field],want,field);p.pin(self.root(root)/'PINS.json',want)
        p.pin(p.HERE/'PINS.json',self.raw['dependencies']['consumer_pins_sha256'])
        for name,value in p.read(p.HERE/'PINS.json').items():p.pin(p.HERE/name,value)
        self.host.require_current_host();self.verify_files();verify_transport_smoke(self);verify_build(self);return self

def verify_build(ctx):
    c=ctx.cc
    native_host=c.strict_json(ctx.pin('host_binding').verify())
    python=c.FilePin.parse('actual supervisor Python',native_host['tools']['python']);python.verify();c.exact(str(Path(sys.executable)),str(python.path),'actual Python executable')
    runtime=c.FilePin.parse('actual Python runtime',native_host['tools']['python_runtime']);runtime.verify()
    p.require(sys.platform=='win32' and hasattr(sys,'dllhandle'),'actual Windows Python runtime handle required')
    import ctypes
    get_name=ctypes.WinDLL('kernel32',use_last_error=True).GetModuleFileNameW
    get_name.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint];get_name.restype=ctypes.c_uint
    buffer=ctypes.create_unicode_buffer(32768);count=get_name(sys.dllhandle,buffer,len(buffer));p.require(0<count<len(buffer),'loaded Python DLL observation failed')
    c.exact(str(Path(buffer.value)).casefold(),str(runtime.path).casefold(),'actual loaded Python DLL')
    b=c.strict_json(ctx.pin('rust_build').verify(),cap=16*1024**2)
    c.exact_keys(b,('schema','host','source_root','source_files','source_tree_sha256','source_revision','dirty_overlay_sha256','target','target_directory','compiler_inputs','features','command','environment_sha256','rustc','cargo','rustc_verbose','cargo_version','compiler_provenance','dependency_closure','build_process','sampler'),'Rust build closure')
    c.exact(b['schema'],'rust-duty-windows-rust-build/v1','build schema');c.exact(b['host'],ctx.host.record(),'build host')
    c.exact(b['source_root'],str(ctx.root('rust_source')),'source root');actual=inventory(ctx.root('rust_source'),c)
    c.exact(b['source_files'],actual,'complete Rust build-source tree');c.exact(b['source_tree_sha256'],p.digest(actual),'source tree hash')
    p.require(re.fullmatch('[0-9a-f]{40}',b['source_revision']) is not None,'source revision required');c.sha(b['dirty_overlay_sha256'])
    p.require(actual.get('examples/sample_viewmodel_clip.rs')==SAMPLER_SOURCE,'actual unchanged sampler source missing')
    for n in ('Cargo.toml','Cargo.lock','build.rs','src/lib.rs','src/viewmodel_animation.rs','src/skinned_asset.rs','src/asset.rs'):
        p.require(n in actual,'complete loader/build closure missing '+n)
    for name,want in p.read(p.HERE/'RUST_REFERENCE_PINS.json').items():
        c.exact(actual.get(name),want,'unchanged Rust loader/math/build '+name)
    c.exact(b['target'],'x86_64-pc-windows-msvc','Windows target');p.require(type(b['features']) is list and all(type(v) is str for v in b['features']) and len(set(b['features']))==len(b['features']),'features inventory')
    for key in ('rustc','cargo'):
        path=check_record(b[key],c);pe_x64(path)
    target_dir=c.ordinary(b['target_directory'],existing=True)
    p.require(not target_dir.is_relative_to(ctx.root('rust_source')) and not ctx.root('rust_source').is_relative_to(target_dir),'build target output must be disjoint from pinned source snapshot')
    expected=[b['cargo']['path'],'build','--locked','--offline','--message-format=json','--target',b['target'],'--target-dir',str(target_dir),'--example','sample_viewmodel_clip']
    if b['features']:expected+=['--features',','.join(b['features'])]
    c.exact(b['command'],expected,'actual build argv');c.sha(b['environment_sha256'])
    p.require(type(b['rustc_verbose']) is str and '\nhost: x86_64-pc-windows-msvc' in b['rustc_verbose'] and '\ncommit-hash: ' in b['rustc_verbose'],'rustc -vV missing')
    p.require(type(b['cargo_version']) is str and b['cargo_version'].startswith('cargo '),'cargo version missing')
    provenance=b['compiler_provenance'];c.exact_keys(provenance,('distribution','manifest','tools'),'compiler provenance')
    p.require(provenance['distribution']=='official-rustup','official compiler provenance required');check_record(provenance['manifest'],c)
    p.require(type(provenance['tools']) is list and provenance['tools'],'linker/SDK/toolchain closure missing')
    for item in provenance['tools']:check_record(item,c)
    dep=b['dependency_closure'];c.exact_keys(dep,('cargo_lock_sha256','metadata','roots'),'dependency closure')
    c.exact(dep['cargo_lock_sha256'],actual['Cargo.lock'],'locked dependencies');metadata=p.read(check_record(dep['metadata'],c))
    p.require(type(metadata.get('packages')) is list and metadata['packages'],'complete cargo metadata missing')
    p.require(type(dep['roots']) is list and dep['roots'],'vendored dependency roots required')
    closures=[(ctx.root('rust_source'),actual)]
    for root in dep['roots']:
        c.exact_keys(root,('path','files','sha256'),'dependency root');tree=inventory(root['path'],c);c.exact(root['files'],tree,'dependency tree');c.exact(root['sha256'],p.digest(tree),'dependency root hash');dependency_root=c.ordinary(root['path']);p.require(not target_dir.is_relative_to(dependency_root) and not dependency_root.is_relative_to(target_dir),'build target overlaps dependency source');closures.append((dependency_root,tree))
    import build_closure
    build_closure.validate_metadata(metadata,closures,c)
    proc=p.read(check_record(b['build_process'],c));c.exact(proc.get('schema'),'rust-duty-windows-rust-build-process/v1','build process schema')
    for key,want in {'host':b['host'],'command':expected,'environment_sha256':b['environment_sha256'],'completed':True,'exit_code':0,'target':b['target'],'source_tree_sha256':b['source_tree_sha256'],'dirty_overlay_sha256':b['dirty_overlay_sha256'],'dependency_closure_sha256':p.digest(dep),'cwd':str(ctx.root('rust_source')),'target_directory':str(target_dir),'target_empty_before_build':True}.items():c.exact(proc.get(key),want,'build '+key)
    for key in ('stdout','stderr'):check_record(proc[key],c)
    sampler=check_record(b['sampler'],c);c.exact(str(sampler),str(ctx.pin('sampler').path),'actual sampler');c.exact(b['sampler']['sha256'],ctx.pin('sampler').sha256,'sampler build hash');pe_x64(sampler)
    build_closure.verify(ctx,b,closures,metadata,target_dir)
    return b


def verify_transport_smoke(ctx):
    c=ctx.cc;c.exact(ctx.pin('transport_review').sha256,TRANSPORT_REVIEW_SHA,'independent transport review');review=c.strict_json(ctx.pin('transport_review').verify())
    c.exact(review['source_pins_sha256'],REVIEWED_TRANSPORT_PINS_SHA,'review source');c.exact(review['blocking_findings'],[],'review blockers')
    c.exact(ctx.pin('transport_smoke').sha256,'0a10a58145fb2d6d9348ecc8a61d0ad2f8f318e7f644a9b46ce9716d386d6b17','actual independent smoke audit pin')
    c.exact(ctx.pin('transport_smoke_summary').sha256,'b14b01a539920f34eec064a1bec1ec2799840c31e89a36e841831a3960c90fa2','actual Windows summary pin')
    smoke=c.strict_json(ctx.pin('transport_smoke').verify());summary=c.strict_json(ctx.pin('transport_smoke_summary').verify())
    for k,v in {'schema':'windows-owned-process-independent-audit/v1','passed':True,'animation_proof':False,'run_id':38871908839,'adapter_pins_sha256':REVIEWED_TRANSPORT_PINS_SHA,'adapter_build_sha256':'8f0df884fc16cf3299db83c5f32477c28b624607ff8b60c4473892ababf241b2','merge_sha':'990a27ede8a793bdf534bacd5271a62d84c9beaa','summary_sha256':ctx.pin('transport_smoke_summary').sha256,'native_windows_test_count':4,'posix_only_skipped':2}.items():c.exact(smoke.get(k),v,'actual smoke audit '+k)
    skips=[{'test':'test_owned_process.TransportTests.test_own_descendant_cleanup_foreign_process_survives','reason':'Linux process-group cleanup test'},{'test':'test_owned_process.TransportTests.test_signal_exit','reason':'POSIX signal exit test'}]
    for k,v in {'schema':'rust-duty-owned-process-tests/v1','tests_run':78,'failures':0,'errors':0,'skipped':skips,'all_executed_tests_passed':True,'actual_windows_transport_smoke_passed':True,'actual_windows_animation_proof':False,'blender_game_or_assets_executed':False,'source_revision':smoke['merge_sha'],'native_windows_tests_defined':4,'pins_verified':True}.items():c.exact(summary.get(k),v,'actual smoke '+k)
    p.require(type(summary.get('host')) is str and summary['host'].startswith('Windows-'),'actual Windows smoke required')
    return smoke
