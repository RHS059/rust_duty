"""Resolve a reviewed relative layout to this one Windows runner's real paths.

Input roles remain byte-pinned by the bridge/native/runtime validators. The
layout has no shell commands or credential channel. Original data is read only.
"""
from __future__ import annotations
import argparse,ctypes,os,re,sys
from pathlib import Path
package_root=Path(__file__).absolute().parent
if any(p.name=='__pycache__' or p.suffix=='.pyc' for p in package_root.iterdir()):raise SystemExit('orchestration package must be cache-free')
sys.path.insert(0,str(package_root))
from workflow_core import *
import orchestrate

def rel(root,value):
    require(type(value) is str and value and not Path(value).is_absolute() and '..' not in Path(value).parts,'relative reviewed layout path required');return str(ordinary(root/value))

def env_subset():
    allowed={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','TEMP','TMP','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','VCTOOLSINSTALLDIR','VCINSTALLDIR','VSINSTALLDIR','WINDOWSSDKDIR','WINDOWSSDKVERSION','WINDOWSSDKBINPATH','WINDOWSSDKVERBINPATH','UNIVERSALCRTSDKDIR','UCRTVERSION','INCLUDE','LIB','LIBPATH','VSCMD_ARG_TGT_ARCH','VSCMD_ARG_HOST_ARCH','PROCESSOR_ARCHITECTURE','PROCESSOR_ARCHITEW6432'}
    # Preserve the observed Windows architecture; never guess or synthesize it.
    # Windows keys are case-insensitive. Reject ambiguous spellings instead of
    # silently selecting a different value while serializing the pinned env.
    architecture={'PROCESSOR_ARCHITECTURE','PROCESSOR_ARCHITEW6432'}
    for key in os.environ:
        require(key.upper() not in architecture or key in architecture,'architecture environment ambiguous')
    require('PROCESSOR_ARCHITECTURE' in os.environ,'architecture environment absent')
    require(os.environ['PROCESSOR_ARCHITECTURE']=='AMD64','architecture environment unsupported')
    require('PROCESSOR_ARCHITEW6432' not in os.environ or os.environ['PROCESSOR_ARCHITEW6432']=='AMD64','architecture environment unsupported')
    result={k:v for k,v in os.environ.items() if k.upper() in allowed}
    require(len({k.upper() for k in result})==len(result),'architecture environment ambiguous')
    require('SYSTEMROOT' in {k.upper() for k in result},'Windows system environment absent')
    # Fixed runtime and build behavior, with no inherited arbitrary overrides.
    result.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',CARGO_TERM_COLOR='never',CI='true')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--layout',required=True);p.add_argument('--layout-sha256',required=True);p.add_argument('--materialized',required=True);p.add_argument('--byte-checkout-receipt',required=True);p.add_argument('--work-root',required=True);p.add_argument('--blender-install-receipt',required=True);p.add_argument('--rust-toolchain-receipt',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    review=orchestrate.reviewed_dependencies();layout=strict_json(pin(a.layout,a.layout_sha256));root=ordinary(a.materialized,True);work=ordinary(a.work_root)
    require(layout['schema']=='rust-duty-onehand-controller-layout/v1','layout schema')
    install=strict_json(a.blender_install_receipt);rust=strict_json(a.rust_toolchain_receipt)
    require(rust['schema']=='rust-duty-onehand-rustup-install/v1' and rust['toolchain']==review['rust_toolchain'],'actual reviewed Rust toolchain receipt required')
    require(os.environ.get('GITHUB_RUN_ID','').isdigit() and os.environ.get('GITHUB_RUN_ATTEMPT','').isdigit(),'actual Actions run identity required')
    session='run-'+os.environ['GITHUB_RUN_ID']+'-attempt-'+os.environ['GITHUB_RUN_ATTEMPT'];candidate='onehand-v6-windows'
    roots={k:rel(root,v) for k,v in layout['roots'].items()};roots['blender_bundle']=install['bundle_root']
    environment=env_subset()
    config={'byte_checkout':file_pin(a.byte_checkout_receipt),'candidate_id':candidate,'session_id':session,'runner_id':'runner-'+digest(os.environ.get('RUNNER_NAME','unknown'))[:24],'run_id':session,'private_root':str(work/'private'),'evidence_root':str(work/'public-evidence'),'roots':roots,'inputs':{k:rel(root,v) for k,v in layout['inputs'].items()},'authored_bridge':rel(root,layout['authored_bridge']),'blender_install_receipt':str(ordinary(a.blender_install_receipt,True)),'native_environment':environment,'runtime_environment':environment,'rust':{'source_root':roots['rust_source'],'source_revision':review['rust_source_revision'],'toolchain':review['rust_toolchain'],'distribution':'official-rustup','target_directory':str(work/'rust-target'),'vendor_root':str(work/'rust-vendor'),'cargo_home':str(work/'cargo-home'),'cargo':rust['cargo']['path'],'rustc':rust['rustc']['path'],'rustup_manifest':rust['manifest']['path'],'toolchain_receipt':str(ordinary(a.rust_toolchain_receipt,True)),'compiler_tool_files':rust['compiler_tool_files'],'features':layout['rust_features']}}
    write_new(Path(a.output),config);print(json.dumps(file_pin(Path(a.output))))
if __name__=='__main__':main()
