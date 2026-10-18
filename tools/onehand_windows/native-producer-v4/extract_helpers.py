"""Source-only extractor. Never imports a frozen top-level Blender program.

Writes source fragments, not animation/geometry data. Exact AST selections and
file/function hashes are independently checked by test_native_producer.py.
"""
import ast, hashlib, json
from pathlib import Path
ROOT = Path(__file__).absolute().parents[2]
HERE = Path(__file__).absolute().parent

def extract(root=ROOT):
    fragments = {}; files = {}
    def tree(rel):
        p=root/rel; raw=p.read_bytes(); files[rel]=hashlib.sha256(raw).hexdigest()
        return ast.parse(raw, filename=rel)
    def put(name, rel, nodes, *, remove_path=False, recipe=False):
        # Serialize AST, preserving all operations and literal values. Formatting
        # is deliberately not a semantic criterion; original source is also pinned.
        original=ast.Module(body=nodes,type_ignores=[])
        src=ast.unparse(original)+'\n'
        fragments[name]={'file':rel,'original_ast_sha256':hashlib.sha256(ast.dump(original,include_attributes=False).encode()).hexdigest(),
            'source':src,'source_sha256':hashlib.sha256(src.encode()).hexdigest(),
            'original_source_segments_sha256':hashlib.sha256(json.dumps([ast.get_source_segment((root/rel).read_text(),n) for n in nodes],ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
            'remove_legacy_search_path':remove_path,'replace_recipe_identity':recipe}
    def functions(rel,names):
        t=tree(rel)
        for name in names:put(name,rel,[next(n for n in t.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name)])
    prefix='onehand-runtime-20261016-r2/'
    functions(prefix+'native-dense/dense_backend.py',['operator_defaults','export_exact_grid','raw_key_grid','import_exact_grid'])
    functions(prefix+'native-window-v2/window_contract.py',['array_hash','native_grid','selection','validate_arrays','linear_value'])
    rel=prefix+'native-window-v2/window_import.py';t=tree(rel)
    put('import_window',rel,[next(n for n in t.body if isinstance(n,ast.FunctionDef))],remove_path=True,recipe=True)
    fragments['import_exact_grid']['remove_legacy_search_path']=True
    rel=prefix+'native-window-v2/sample_source.py';t=tree(rel);b=t.body[-1].body;tr=next(n for n in b if isinstance(n,ast.Try))
    for name in ('camera_projection','mesh_samples'):
        put(name,rel,[next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name==name)])
    put('source_capture',rel,b[12:21]);put('source_select',rel,b[21:49]);put('source_restore',rel,tr.finalbody)
    put('source_rows',rel,tr.body[:3]) # mkdir rows/skins; exact full source sample loop
    functions(prefix+'native-rigid-v2/sample_rigid.py',['geometry'])
    for f,names in [('source_integrity.py',['digest','action_fingerprint','nla_snapshot','snapshot']),('validate_directional_source.py',['atom','props','matrix','extra_snapshot'])]:
        functions('recovery/animation-queue/runs/onehand-r5-from-reconstructed-r4/integrity/'+f,names)
    rel=prefix+'runtime-conversion-v2/native_runtime.py';t=tree(rel);b=t.body[51]
    put('runtime_static',rel,t.body[28:50]);put('runtime_geometry',rel,b.body[:28]);put('runtime_block',rel,b.orelse[4:6]+b.orelse[7:10])
    rel=prefix+'native-window-v2/verify_window.py';t=tree(rel);b=t.body[41]
    put('import_pose_setup',rel,t.body[33:41]);put('bounded_control_compare',rel,b.body[1:-1])
    # Full exact focus math before packaging/identity bookkeeping. Last checks
    # include old SOURCE_SHA, so those checks are supplied by the new wrapper.
    put('focus_measure',rel,b.orelse[:-3])
    functions(prefix+'native-rigid-v2/rigid_geometry.py',['geometry_record'])
    functions(prefix+'native-rigid-v2/rigid_bytes.py',['GeometryBytes','canonical_buffers'])
    # Pin safe complete reusable helpers too. No import-time invocation.
    for f in ['vrpack.py','vrskin.py','vrview.py','single_stack_fbx.py','export_viewmodel.py','import_fbx_viewmodel.py','prone_camera_pair.py']:
        tree('onehand-runtime-20261016/importer-patch/tools/'+f)
    tree(prefix+'runtime-conversion-v2/assemble_runtime.py')
    return {'schema':'rust-duty-native-audited-fragments/v1','files':files,'fragments':fragments}

if __name__=='__main__':
    data=extract()
    with (HERE/'AUDITED_FRAGMENTS.json').open('x') as f:json.dump(data,f,indent=2,sort_keys=True);f.write('\n')
