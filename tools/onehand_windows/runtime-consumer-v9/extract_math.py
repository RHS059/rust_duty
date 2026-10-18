"""Reproducible source-only extraction; no original module is imported."""
import ast, hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
SELECT={
 'common':('onehand-runtime-20261016-r2/runtime-parity/onehand_r2_common.py',[
 'FrozenMap','validate_runtime_grid','validate_timing_policy','validate_runtime_times','validate_patches','validate_import_admission','validate_raw_key_grid']),
 'parity':('onehand-runtime-20261016-r2/runtime-parity/verify_onehand_r2.py',[
 'load_row','Checker','validate_loading_row','summarize']),
 'geometry':('prone-r15-runtime-20261016/source/tools/verify_prone_r15_runtime.py',[
 'finite','matrix','skeleton_parents','read_geometry','nearest_indices','bounded_nearest_indices','FixedCorrespondence','max_position_error','transformed','numeric','visible_matrix','exact_time']),
 'scanner':('onehand-runtime-20261016-r2/runtime-parity/bounded_vra.py',['scan_buffer','scan_vra','metadata_only']),
 'window':('onehand-runtime-20261016-r2/runtime-parity/window_admission.py',['sha_string','expected_selection','validate_actions','validate_window','exact_recursive']),
}
def main():
    out={}; pins={}
    for group,(relative,names) in SELECT.items():
        raw=(ROOT/relative).read_bytes(); pins[relative]=hashlib.sha256(raw).hexdigest(); source=raw.decode();tree=ast.parse(source)
        lines=source.splitlines(keepends=True); selected={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        fragments={}
        for name in names:
            node=selected[name];fragment=''.join(lines[node.lineno-1:node.end_lineno])
            fragments[name]={'source':fragment,'byte_sha256':hashlib.sha256(fragment.encode()).hexdigest(), 'ast_sha256':hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()}
        out[group]={'source_path':relative,'source_sha256':pins[relative],'definitions':fragments}
    for name in ('vrpack','vrskin','vrview'):
        p='onehand-runtime-20261016/importer-patch/tools/'+name+'.py'; pins[p]=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
    for name in ('admit_candidate','focused_runtime','serial_r2','conversion_admission','test_bounded_vra'):
        p='onehand-runtime-20261016-r2/runtime-parity/'+name+'.py';pins[p]=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
    for name,value in [('MATH_FRAGMENTS.json',out),('ORIGINAL_PINS.json',pins)]:
        (HERE/name).write_text(json.dumps(value,indent=2)+'\n')
if __name__=='__main__':main()
