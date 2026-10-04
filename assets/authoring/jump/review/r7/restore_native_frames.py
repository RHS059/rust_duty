"""Restore the exact existing r7 native PNG archive using only Python's standard library."""
import argparse,hashlib,json,os,zipfile
from pathlib import Path

def file_sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while data:=f.read(1024*1024):h.update(data)
 return h.hexdigest()

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();root=Path(__file__).resolve().parent
 manifest=json.loads((root/'native_evidence.manifest.json').read_text());index=json.loads((root/manifest['frame_index']).read_text());expected=manifest['archive'];output=args.output or root/expected['filename']
 if output.exists():
  if output.stat().st_size==expected['bytes'] and file_sha(output)==expected['sha256']:
   print(f'Already verified: {output}');return
  raise SystemExit('Refusing to overwrite an existing nonmatching output')
 partpaths=[]
 for part in manifest['parts']:
  path=(root/part['path']).resolve();path.relative_to(root)
  if not path.is_file() or path.stat().st_size!=part['bytes'] or file_sha(path)!=part['sha256']:raise SystemExit(f'Missing or invalid part: {part["path"]}')
  partpaths.append(path)
 output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_name(output.name+'.partial')
 with temp.open('xb') as dst:
  for path in partpaths:
   with path.open('rb') as src:
    while data:=src.read(1024*1024):dst.write(data)
 if temp.stat().st_size!=expected['bytes'] or file_sha(temp)!=expected['sha256']:raise SystemExit('Restored archive hash mismatch; partial output retained for inspection')
 with zipfile.ZipFile(temp) as z:
  if z.testzip() is not None:raise SystemExit('ZIP CRC failed')
  names={r['archive_path'] for r in index['records']}
  if set(z.namelist())!=names or len(z.namelist())!=expected['members']:raise SystemExit('Unexpected archive members')
  for r in index['records']:
   data=z.read(r['archive_path'])
   if len(data)!=r['bytes'] or hashlib.sha256(data).hexdigest()!=r['sha256']:raise SystemExit(f'Native PNG mismatch: {r["archive_path"]}')
 os.replace(temp,output)
 print(f'Verified {expected["members"]} original PNGs: {output}')
 print(f'SHA256 {expected["sha256"]}')
if __name__=='__main__':main()
