"""Restore an exact isolated technical packet; never activates runtime assets."""
import argparse,gzip,hashlib,io,json,tarfile
from pathlib import Path,PurePosixPath
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=Path(__file__).with_name('packet_manifest.json'));p.add_argument('--output',type=Path,required=True);a=p.parse_args();m=json.loads(a.manifest.read_text());root=a.manifest.parent
if a.output.exists():raise SystemExit('Refusing an existing output path')
def valid(data,row):
 if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Size/hash mismatch: '+row['path'])
parts=[]
for row in m['parts']:
 path=PurePosixPath(row['path'])
 if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe part path')
 data=(root/row['path']).read_bytes();valid(data,row);parts.append(data)
archive=b''.join(parts)
if len(archive)!=m['archive_bytes'] or hashlib.sha256(archive).hexdigest()!=m['archive_sha256']:raise ValueError('Archive identity mismatch')
expected={r['path']:r for r in m['members']};payload={}
with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)),mode='r:') as tar:
 for member in tar.getmembers():
  path=PurePosixPath(member.name)
  if not member.isfile() or path.is_absolute() or '..' in path.parts or member.name not in expected or member.name in payload:raise ValueError('Unexpected/unsafe archive member')
  data=tar.extractfile(member).read();valid(data,expected[member.name]);payload[member.name]=data
if set(payload)!=set(expected):raise ValueError('Missing archive member')
a.output.mkdir(parents=True)
for name,data in payload.items():
 dest=a.output/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
print(json.dumps({'verified':True,'archive_sha256':m['archive_sha256'],'source_sha256':m['source_sha256'],'files':len(payload),'output':str(a.output),'runtime_activation':False}))
