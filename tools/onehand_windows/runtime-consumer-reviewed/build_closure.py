"""Read-only build-input closure, including rustc dep-info and generated inputs.

No source subtree is omitted. An authenticated controller must capture the exact
Cargo JSON stdout, dep-info and generated-input producer receipts at build time.
Self-hashes remain consistency evidence, not proof that a compiler ran.
"""
from pathlib import Path
import re
import pinned_math as p

def membership(path,closures,cc):
    path=cc.ordinary(path,existing=True)
    matches=[]
    for root,files in closures:
        if path.is_relative_to(root):
            key=path.relative_to(root).as_posix()
            if key in files:matches.append(files[key])
    p.require(len(matches)==1,'build input absent/ambiguous in actual pinned inventory: '+str(path))
    p.pin(path,matches[0]);return path

def validate_metadata(metadata,closures,cc):
    packages=metadata.get('packages');p.require(type(packages) is list and packages,'complete Cargo package metadata required')
    ids=[];targets={}
    for package in packages:
        ident=package['id'];p.require(type(ident) is str and ident and ident not in ids,'Cargo package identity duplicate');ids.append(ident)
        membership(package['manifest_path'],closures,cc)
        p.require(type(package.get('targets')) is list and package['targets'],'Cargo target source inventory missing')
        for target in package['targets']:
            membership(target['src_path'],closures,cc)
            key=(ident,target['name'],tuple(target['kind']));p.require(key not in targets,'duplicate Cargo target');targets[key]=target
    resolve=metadata.get('resolve');p.require(type(resolve) is dict and type(resolve.get('nodes')) is list,'locked complete Cargo resolve graph required')
    p.require(len(resolve['nodes'])==len(ids) and {n['id'] for n in resolve['nodes']}==set(ids),'Cargo package/resolve inventory differs')
    for node in resolve['nodes']:
        p.require(type(node.get('dependencies')) is list and set(node['dependencies'])<=set(ids),'Cargo dependency node outside inventory')
    return targets

def dep_info_paths(raw):
    """Bounded rustc Make dep-info parser; no shell, glob or variable expansion.

Accept LF/CRLF, escaped whitespace/#/colon/backslash, Windows drive and UNC
spelling. Targets are ignored; every dependency rule contributes input paths.
Malformed rules and Make variable expansion are rejected.
"""
    p.require(type(raw) is bytes and 0<len(raw)<=8*1024**2,'dep-info byte cap')
    text=raw.decode('utf-8');p.require('\0' not in text and '$' not in text,'unsupported dep-info control/expansion')
    text=text.replace('\\\r\n','').replace('\\\n','');paths=[]
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):continue
        split=None;escaped=False
        for i,ch in enumerate(line):
            if escaped:escaped=False;continue
            if ch=='\\' and i+1<len(line) and line[i+1] in ' \t#:\\':escaped=True;continue
            if ch==':' and (i+1==len(line) or line[i+1].isspace()):split=i;break
        p.require(split is not None,'invalid dep-info rule')
        rest=line[split+1:];tokens=[];token=[];i=0
        while i<len(rest):
            ch=rest[i]
            if ch=='\\' and i+1<len(rest) and rest[i+1] in ' \t#:\\':token.append(rest[i+1]);i+=2;continue
            if ch.isspace():
                if token:tokens.append(''.join(token));token=[]
            elif ch=='#':p.require(not token,'unescaped dep-info comment in path');break
            else:token.append(ch)
            i+=1
        if token:tokens.append(''.join(token))
        paths.extend(tokens)
    p.require(paths,'dep-info has no compiler input paths');return sorted(set(paths))

def verify(ctx,build,closures,metadata,target_dir):
    from runtime_context import check_record
    c=ctx.cc;targets=validate_metadata(metadata,closures,c)
    report=p.read(check_record(build['compiler_inputs'],c,ctx.candidate_root))
    c.exact_keys(report,('schema','command_sha256','source_tree_sha256','dependency_closure_sha256','cargo_messages','invocations'),'compiler input closure')
    for k,want in {'schema':'rust-duty-rust-compiler-input-closure/v1','command_sha256':p.digest(build['command']),'source_tree_sha256':build['source_tree_sha256'],'dependency_closure_sha256':p.digest(build['dependency_closure'])}.items():p.exact(report[k],want,'compiler closure '+k)
    messages=check_record(report['cargo_messages'],c,ctx.candidate_root);p.require(report['cargo_messages']==p.read(check_record(build['build_process'],c))['stdout'],'Cargo messages must be actual build stdout')
    artifacts={};out_dirs=set();build_success=False
    with messages.open('rb') as stream:
        for line in stream:
            p.require(len(line)<=8*1024**2,'Cargo JSON line cap');row=p.loads(line)
            if row.get('reason')=='compiler-artifact':
                key=(row['package_id'],row['target']['name'],tuple(row['target']['kind']));p.require(key in targets,'compiled target absent from locked metadata')
                p.exact(row['target']['src_path'],targets[key]['src_path'],'compiled root source')
                identity=p.digest(row);p.require(identity not in artifacts,'duplicate Cargo artifact');artifacts[identity]=row
            elif row.get('reason')=='build-script-executed':
                directory=c.ordinary(row['out_dir'],existing=True);p.require(directory.is_relative_to(target_dir),'Cargo OUT_DIR outside explicit target directory');out_dirs.add(directory)
            elif row.get('reason')=='build-finished':p.require(row.get('success') is True,'Cargo build failed');build_success=True
    p.require(build_success and artifacts,'complete successful Cargo message stream required')
    p.require(any(a.get('executable')==build['sampler']['path'] for a in artifacts.values()),'sampler not an actual Cargo executable output')
    invocations=report['invocations'];p.require(type(invocations) is list and len(invocations)==len(artifacts),'every Cargo artifact needs compiler input closure')
    p.require({r.get('artifact_sha256') for r in invocations}==set(artifacts),'compiler artifact coverage differs')
    for invocation in invocations:
        c.exact_keys(invocation,('artifact_sha256','dep_info','generated_inputs'),'compiler invocation')
        artifact=artifacts[invocation['artifact_sha256']];dep=check_record(invocation['dep_info'],c,target_dir);raw=dep.read_bytes();names=dep_info_paths(raw)
        inputs=[]
        for name in names:
            path=Path(name)
            if not path.is_absolute():path=ctx.root('rust_source')/path
            path=c.ordinary(path,existing=True);inputs.append(path)
        p.require(Path(artifact['target']['src_path']) in inputs,'dep-info omits crate root')
        generated=invocation['generated_inputs'];p.require(type(generated) is list,'generated input inventory required');declared={}
        for item in generated:
            c.exact_keys(item,('file','producer'),'generated compiler input');file=check_record(item['file'],c,target_dir)
            p.require(str(file) not in declared,'duplicate generated compiler input');declared[str(file)]=item['file']
            producer_path=check_record(item['producer'],c,ctx.candidate_root);producer=p.read(producer_path)
            c.exact_keys(producer,('schema','build_process','source_tree_sha256','dependency_closure_sha256','out_dir','outputs'),'generated input producer')
            for key,want in {'schema':'rust-duty-cargo-generated-inputs/v1','build_process':build['build_process'],'source_tree_sha256':build['source_tree_sha256'],'dependency_closure_sha256':p.digest(build['dependency_closure'])}.items():p.exact(producer[key],want,'generated producer '+key)
            check_record(producer['build_process'],c,ctx.candidate_root)
            out_dir=c.ordinary(producer['out_dir'],existing=True);p.require(out_dir in out_dirs and file.is_relative_to(out_dir),'generated input not in observed Cargo build-script OUT_DIR')
            p.require(type(producer['outputs']) is list and producer['outputs'],'generated output inventory')
            p.require(len({r['path'] for r in producer['outputs']})==len(producer['outputs']),'duplicate generated producer outputs')
            for rec in producer['outputs']:check_record(rec,c,out_dir)
            p.require(item['file'] in producer['outputs'],'generated file not linked to actual Cargo producer output')
        actual_generated=set()
        for path in inputs:
            if path.is_relative_to(target_dir):p.require(str(path) in declared,'unaccounted generated compiler input');actual_generated.add(str(path))
            else:membership(path,closures,c)
        p.require(actual_generated==set(declared),'unused/missing generated input records')
    return report
