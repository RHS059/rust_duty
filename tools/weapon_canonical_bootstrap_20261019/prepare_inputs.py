"""Prepare the pinned sources for one-time canonical assembly; no Git writes."""
import argparse,importlib.util,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
FILES=['assemble_weapon_library.py','verify_weapon_library.py','REPOSITORY_SOURCE_INPUTS.json','jump_landing_patch.py','locomotion-export-config.json','ads-export-config.json','directional-export-config.json','jump-export-config.json']
def main():
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--accept-drive-warning',action='store_true');a=p.parse_args()
 repo=a.repo.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
 module=repo/'tools/runtime_recovery_20261019/restore.py'
 spec=importlib.util.spec_from_file_location('reviewed_runtime_restore',module);restore=importlib.util.module_from_spec(spec);spec.loader.exec_module(restore)
 m=json.loads((HERE/'source_manifest.json').read_text())
 for r in m['repository']:
  path=Path(r['path']);name=Path(r['local_name'])
  restore.require(not path.is_absolute() and '..' not in path.parts and len(name.parts)==1,'unsafe source path')
  source=repo/path;target=out/name
  restore.require(not any(x.is_symlink() for x in [source,*source.parents]),'source symlink rejected')
  restore.require(not target.is_symlink(),'destination symlink rejected');restore.verify_file(source,r)
  if target.exists():restore.verify_file(target,r)
  else:shutil.copyfile(source,target);restore.verify_file(target,r)
 for r in m['drive']:
  restore.require(len(Path(r['name']).parts)==1,'unsafe Drive destination')
  restore.download(r,out,accept_warning=a.accept_drive_warning)
 for n in FILES:
  if (HERE/n).resolve()!=(out/n).resolve():shutil.copyfile(HERE/n,out/n)
 (out/'source_manifest.json').write_text(json.dumps(m,indent=2))
 print(json.dumps({'prepared_sources':len(m['drive'])+len(m['repository']),'output':str(out),'canonical_path':m['canonical_path']}))
if __name__=='__main__':main()
