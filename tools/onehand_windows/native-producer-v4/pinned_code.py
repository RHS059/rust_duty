"""Exact source/function closure, isolated helpers, and narrowly audited relocation.

No bpy import or frozen program execution occurs during planning. The only AST
changes remove two obsolete search-path statements and relocate one recipe pin.
All transform, quaternion history, geometry and frame packing operations are exact.
"""
import ast, builtins, copy, hashlib, inspect, json, sys, types, uuid
from pathlib import Path
HERE=Path(__file__).absolute().parent
CONTEXT_PINS_SHA='3162a4c5bbc50daa13ec1c84972b0e4b56c2221a909d1aa2c10617c912b0d801'

def require(ok,message):
    if not ok: raise ValueError(message)
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(65536),b''):h.update(b)
    return h.hexdigest()
def load_context(package):
    package=Path(package)
    require(file_sha(package/'PINS.json')==CONTEXT_PINS_SHA,'exact context v2 freeze required')
    pins=json.loads((package/'PINS.json').read_text())
    for name,sha in pins.items():
        require(Path(name).name==name and file_sha(package/name)==sha,'context freeze differs: '+name)
    return isolated_module('candidate_context',package/'candidate_context.py',{})

def isolated_module(name,path,loaded,tree=None,values=None):
    def importer(name,globals=None,locals=None,fromlist=(),level=0):
        if name in loaded:
            require(level==0,'relative helper import forbidden');return loaded[name]
        return builtins.__import__(name,globals,locals,fromlist,level)
    private='_native_'+uuid.uuid4().hex+'_'+name;module=types.ModuleType(private);module.__file__=str(path)
    module.__dict__.update(values or {});module.__builtins__={**vars(builtins),'__import__':importer}
    sys.modules[private]=module
    try:exec(compile(tree if tree is not None else Path(path).read_bytes(),str(path),'exec',dont_inherit=True),module.__dict__)
    finally:del sys.modules[private]
    return module

def fragments():
    data=json.loads((HERE/'AUDITED_FRAGMENTS.json').read_text())
    for rec in data['fragments'].values():
        require(hashlib.sha256(rec['source'].encode()).hexdigest()==rec['source_sha256'],'fragment source hash differs')
        require(hashlib.sha256(ast.dump(ast.parse(rec['source']),include_attributes=False).encode()).hexdigest()==rec['original_ast_sha256'],'fragment AST differs')
    return data

def verify_originals(root):
    data=fragments()
    for rel,wanted in data['files'].items():
        require(file_sha(Path(root)/rel)==wanted,'audited original changed: '+rel)
    return data

class Relocate(ast.NodeTransformer):
    def __init__(self,rec):self.rec=rec;self.paths=0;self.recipes=0
    def visit_Expr(self,node):
        if self.rec['remove_legacy_search_path'] and ast.unparse(node)=="sys.path.insert(0, str(ROOT / 'onehand-runtime-20261016/importer-patch/tools'))":
            self.paths+=1;return None
        return self.generic_visit(node)
    def visit_Call(self,node):
        if self.rec['replace_recipe_identity'] and ast.unparse(node)=="sha(HERE / 'pins.json')":
            self.recipes+=1;return ast.copy_location(ast.Name(id='helper_recipe_sha256',ctx=ast.Load()),node)
        return self.generic_visit(node)

def fragment_tree(name):
    rec=fragments()['fragments'][name];r=Relocate(rec);tree=r.visit(ast.parse(rec['source']))
    require(r.paths==int(rec['remove_legacy_search_path']) and r.recipes==int(rec['replace_recipe_identity']),'unexpected relocation structure')
    return ast.fix_missing_locations(tree)

def execute(name,namespace):
    exec(compile(fragment_tree(name),'audited:'+name,'exec',dont_inherit=True),namespace)

def helpers(root,base):
    """Called only after native admission; helper imports cannot be shadowed."""
    data=verify_originals(root);loaded={};root=Path(root);tools=root/'onehand-runtime-20261016/importer-patch/tools'
    for name in ('vrpack','vrskin','vrview','single_stack_fbx'):
        loaded[name]=isolated_module(name,tools/(name+'.py'),loaded)
    for name,func in (('import_fbx_viewmodel','patch_importer'),('export_viewmodel','export_glb')):
        path=tools/(name+'.py');tree=ast.parse(path.read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==func)
        loaded[name]=isolated_module(name,path,loaded,ast.Module(body=[node],type_ignores=[]),{**base,'single_stack_fbx':loaded['single_stack_fbx']})
    def importer(name,globals=None,locals=None,fromlist=(),level=0):
        if name in loaded:return loaded[name]
        return builtins.__import__(name,globals,locals,fromlist,level)
    env={**base,**loaded,'__builtins__':{**vars(builtins),'__import__':importer}}
    for name in ('array_hash','native_grid','selection','validate_arrays','linear_value','operator_defaults','export_exact_grid','raw_key_grid','import_exact_grid','import_window','camera_projection','mesh_samples','geometry_record','geometry','canonical_buffers'):
        if name=='canonical_buffers':
            # dataclass requires its definition to be visible during creation.
            m=isolated_module('rigid_bytes',root/'onehand-runtime-20261016-r2/native-rigid-v2/rigid_bytes.py',loaded)
            env[name]=m.canonical_buffers
        else:execute(name,env)
    snap={**base}
    for name in ('digest','action_fingerprint','nla_snapshot','snapshot','atom','props','matrix','extra_snapshot'):execute(name,snap)
    env.update({k:snap[k] for k in ('snapshot','extra_snapshot','atom','action_fingerprint')})
    return env
