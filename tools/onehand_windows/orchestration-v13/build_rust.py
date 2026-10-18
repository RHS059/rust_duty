"""Create the strict consumer build closure from an actual fresh Cargo build.

No guessed inner build-script invocation is recorded. Generated-input provenance
is the observed supervised whole Cargo build and its actual OUT_DIR events.
"""
from __future__ import annotations
from pathlib import Path
from workflow_core import *
import source_selection

TARGET='x86_64-pc-windows-msvc'

def disjoint_build_roots(roots):
    roots=[ordinary(p) for p in roots]
    for i,p in enumerate(roots):
        for q in roots[i+1:]:
            require(not p.is_relative_to(q) and not q.is_relative_to(p),'Rust build roots overlap')

class FreshCargoTarget:
    """One newly created output directory, never reused, emptied or replaced.

    Cargo metadata may write compiler probes. Preparation owns a different
    directory from every real build; its files are retained as private evidence
    and never included in the compiler input closure.
    """
    def __init__(self,path):
        self.path=ordinary(path)
        require(not self.path.exists(),'fresh Cargo target directory required')
        self.path.mkdir(parents=True)
        self.identity=self._identity()
    def _identity(self):
        path=ordinary(self.path,True);info=path.stat()
        require(stat.S_ISDIR(info.st_mode),'owned Cargo target must be a directory')
        return (info.st_dev,info.st_ino)
    def verify(self):
        require(self._identity()==self.identity,'owned Cargo target directory replaced')
    def require_empty(self,message):
        self.verify();require(not any(self.path.iterdir()),message)
    def run(self,commands,label,argv,cwd,*,environment,**kwargs):
        self.verify()
        require(environment.get('CARGO_TARGET_DIR')==str(self.path),'owned Cargo target environment differs')
        result=commands.run(label,argv,cwd,environment=environment,**kwargs)
        self.verify();return result

def cargo_events(path):
    rows=[]
    with Path(path).open('rb') as f:
        for line in f:
            require(len(line)<=8*1024**2,'Cargo JSON line cap')
            row=json.loads(line);require(type(row) is dict,'Cargo JSON object required');rows.append(row)
    require(any(r.get('reason')=='build-finished' and r.get('success') is True for r in rows),'successful complete Cargo stream required')
    return rows

def dependencies_for(path,source,parser):
    return [ordinary(p if Path(p).is_absolute() else source/p,True) for p in parser(Path(path).read_bytes())]

def select_dep_info(artifact,paths,source,parser,parsed=None):
    root=ordinary(artifact['target']['src_path'],True)
    found=[p for p in paths if root in (parsed[p] if parsed is not None else dependencies_for(p,source,parser))]
    # Prefer the exact output-corresponding rustc dep-info filename. A fresh
    # target prevents stale-cache contenders; remaining ambiguity is a blocker.
    stems={Path(f).stem.removeprefix('lib') for f in artifact['filenames']}
    direct=[p for p in found if p.stem in stems]
    if len(direct)==1:return direct[0]
    require(len(found)==1,'missing/ambiguous compiler dep-info for '+artifact['target']['name'])
    return found[0]

def compiler_report(build,process,events,target,source,parser,candidate):
    artifacts=[r for r in events if r.get('reason')=='compiler-artifact']
    require(len({digest(a) for a in artifacts})==len(artifacts),'duplicate Cargo artifacts')
    outs={ordinary(r['out_dir'],True) for r in events if r.get('reason')=='build-script-executed'}
    require(all(p.is_relative_to(target) for p in outs),'foreign Cargo OUT_DIR')
    producers={}
    for i,out in enumerate(sorted(outs)):
        files=[record(p) for p in sorted(out.rglob('*')) if p.is_file()]
        if not files:continue
        value={'schema':'rust-duty-cargo-generated-inputs/v1','build_process':process,'source_tree_sha256':build['source_tree_sha256'],'dependency_closure_sha256':digest(build['dependency_closure']),'out_dir':str(out),'outputs':files}
        path=candidate/'build'/f'generated-{i:03d}.json';write_new(path,value);producers[out]=record(path)
    parsed={}
    for path in sorted(target.rglob('*.d')):
        try:parsed[path]=dependencies_for(path,source,parser)
        except (ValueError,OSError,UnicodeError):
            # Non-rustc C/build-tool .d files can use other grammars. They do
            # not satisfy any artifact; an unmatched Rust artifact still fails.
            continue
    paths=list(parsed);invocations=[]
    for artifact in artifacts:
        dep=select_dep_info(artifact,paths,source,parser,parsed);generated=[]
        for f in parsed[dep]:
            if f.is_relative_to(target):
                matches=[p for p in outs if f.is_relative_to(p)];require(len(matches)==1,'generated compiler input has no unique observed OUT_DIR')
                generated.append({'file':record(f),'producer':producers[matches[0]]})
        invocations.append({'artifact_sha256':digest(artifact),'dep_info':record(dep),'generated_inputs':generated})
    return {'schema':'rust-duty-rust-compiler-input-closure/v1','command_sha256':digest(build['command']),'source_tree_sha256':build['source_tree_sha256'],'dependency_closure_sha256':digest(build['dependency_closure']),'cargo_messages':strict_json(process['path'])['stdout'],'invocations':invocations}

def create_build(config,consumer,commands,candidate,host):
    c=config['rust'];source=ordinary(c['source_root'],True);target=ordinary(c['target_directory']);vendor=ordinary(c['vendor_root']);cargo_home=ordinary(c['cargo_home'])
    preparation_target=target.with_name(target.name+'-preparation')
    disjoint_build_roots([source,target,preparation_target,vendor,cargo_home,candidate])
    require(not any(p.exists() for p in (target,preparation_target,vendor,cargo_home)),'fresh Rust build target/vendor/home required')
    before=inventory(source);revision=c['source_revision'];checkout=strict_json(pin(config['byte_checkout']['path'],config['byte_checkout']['sha256']))
    expected={r['destination'][len('rust-source/'):]:r['sha256'] for r in checkout['files'] if r['destination'].startswith('rust-source/') and r['ref']==revision}
    require(before==expected,'Rust snapshot must exactly match observed Git blobs for reviewed revision')
    source_selection.verify(before,revision,c['features'])
    require(c['toolchain']==source_selection.TOOLCHAIN,'exact reviewed Rust Windows toolchain required')
    require(re.fullmatch('[0-9a-f]{40}',revision) is not None,'full reviewed source revision')
    for n,h in consumer.pinned_math.read(consumer.pinned_math.HERE/'RUST_REFERENCE_PINS.json').items():require(before.get(n)==h,'unchanged reviewed Rust source differs: '+n)
    cargo=record(c['cargo']);rustc=record(c['rustc']);manifest=record(c['rustup_manifest'])
    # These are explicitly selected official-rustup executables; distribution
    # and vendor/toolchain provenance are additionally pinned by the installer.
    require(c['distribution']=='official-rustup','official Rust distribution required')
    toolchain_receipt=strict_json(c['toolchain_receipt']);require(toolchain_receipt['cargo']==cargo and toolchain_receipt['rustc']==rustc and toolchain_receipt['manifest']==manifest,'actual installed Rust toolchain receipt differs')
    require(toolchain_receipt['toolchain']==source_selection.TOOLCHAIN,'actual toolchain receipt differs')
    compiler_tools=[record(p) for p in c['compiler_tool_files']];require(compiler_tools,'explicit linker/SDK/toolchain files required')
    require(compiler_tools==toolchain_receipt['compiler_tools'],'installed linker/SDK files changed')
    env=dict(commands.environment);env.update({'RUSTC':rustc['path'],'CARGO_HOME':str(cargo_home),'CARGO_TARGET_DIR':str(target),'CARGO_INCREMENTAL':'0','CARGO_BUILD_JOBS':'1'})
    cargo_home.mkdir(parents=True);build_target=FreshCargoTarget(target);preparation=FreshCargoTarget(preparation_target)
    preparation_env={**env,'CARGO_TARGET_DIR':str(preparation_target)}
    candidate.joinpath('build').mkdir(parents=True,exist_ok=True)
    rust_version=preparation.run(commands,'rustc-version',[rustc['path'],'-vV'],source,environment=preparation_env)
    source_selection.verify_compiler(Path(rust_version['stdout']['path']).read_text())
    cargo_version=preparation.run(commands,'cargo-version',[cargo['path'],'-V'],source,environment=preparation_env)
    vendor_result=preparation.run(commands,'cargo-vendor',[cargo['path'],'vendor','--locked','--versioned-dirs',str(vendor)],source,environment=preparation_env,stdout_cap=16*1024**2)
    # Use Cargo's actual emitted source replacement config, not a guessed recipe.
    raw=Path(vendor_result['stdout']['path']).read_bytes();require(raw and len(raw)<1024**2,'bounded Cargo vendor config required')
    config_path=cargo_home/'config.toml'
    with config_path.open('xb') as f:f.write(raw)
    config_record=record(config_path)
    features=c['features'];require(type(features) is list and all(type(v) is str for v in features) and len(features)==len(set(features)),'explicit unique features')
    metadata_argv=[cargo['path'],'metadata','--locked','--offline','--format-version','1']
    if features:metadata_argv+=['--features',','.join(features)]
    metadata_run=preparation.run(commands,'cargo-metadata',metadata_argv,source,environment=preparation_env,stdout_cap=32*1024**2)
    metadata=record(metadata_run['stdout']['path']);vendor_before=inventory(vendor)
    dependency={'cargo_lock_sha256':before['Cargo.lock'],'metadata':metadata,'roots':[{'path':str(vendor),'files':vendor_before,'sha256':digest(vendor_before)}]}
    require(inventory(source)==before,'source changed during dependency preparation')
    build_target.require_empty('build target must be empty immediately before Cargo build')
    features=c['features'];require(type(features) is list and all(type(v) is str for v in features) and len(features)==len(set(features)),'explicit unique features')
    argv=[cargo['path'],'build','--locked','--offline','--message-format=json','--target',TARGET,'--target-dir',str(target),'--example','sample_viewmodel_clip']
    if features:argv+=['--features',','.join(features)]
    result=build_target.run(commands,'cargo-build',argv,source,environment=env,stdout_cap=64*1024**2,reserve=2*GIB)
    require(inventory(source)==before and inventory(vendor)==vendor_before,'source/dependency changed during build')
    for tool in (cargo,rustc,manifest,*compiler_tools):pin(tool['path'],tool['sha256'])
    pin(config_path,config_record['sha256'])
    events=cargo_events(result['stdout']['path'])
    samplers=[r['executable'] for r in events if r.get('reason')=='compiler-artifact' and r.get('target',{}).get('name')=='sample_viewmodel_clip' and r.get('executable')]
    require(len(samplers)==1,'one actual Cargo sampler executable required')
    process={'schema':'rust-duty-windows-rust-build-process/v1','host':host,'command':argv,'cwd':str(source),'environment_sha256':digest(env),'completed':True,'exit_code':0,'target':TARGET,'target_directory':str(target),'target_empty_before_build':True,'source_tree_sha256':digest(before),'dirty_overlay_sha256':digest({}),'dependency_closure_sha256':digest(dependency),'stdout':result['stdout'],'stderr':result['stderr'],'owned_process_terminal':result['terminal']}
    process_path=candidate/'build'/'build-process.json';write_new(process_path,process)
    build={'schema':'rust-duty-windows-rust-build/v1','host':host,'source_root':str(source),'source_files':before,'source_tree_sha256':digest(before),'source_revision':revision,'dirty_overlay_sha256':digest({}),'target':TARGET,'target_directory':str(target),'features':features,'command':argv,'environment_sha256':digest(env),'rustc':rustc,'cargo':cargo,'rustc_verbose':Path(rust_version['stdout']['path']).read_text(),'cargo_version':Path(cargo_version['stdout']['path']).read_text(),'compiler_provenance':{'distribution':'official-rustup','manifest':manifest,'tools':[*compiler_tools,config_record,record(c['toolchain_receipt'])]},'dependency_closure':dependency,'build_process':record(process_path),'sampler':record(samplers[0])}
    report=compiler_report(build,record(process_path),events,target,source,consumer.build_closure.dep_info_paths,candidate)
    report_path=candidate/'build'/'compiler-inputs.json';write_new(report_path,report);build['compiler_inputs']=record(report_path)
    path=candidate/'rust-build.json';write_new(path,build);return file_pin(path),file_pin(samplers[0])
