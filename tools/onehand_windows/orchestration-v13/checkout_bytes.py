#!/usr/bin/env python3
"""Fresh explicit Git-blob materialization: no checkout filters/CRLF conversion.

The controller receives a reviewed manifest from the exact Git commit before any
proof-package import. Only allowlisted original source and named existing public
baseline/canonical data may materialize. No network or Git writes occur here.
"""
from __future__ import annotations
import argparse,hashlib,json,re,shutil,stat,subprocess,types
from pathlib import Path

def require(v,m):
    if not v:raise ValueError(m)

def relative(value):
    require(type(value) is str and value and '\\' not in value and '\0' not in value,'invalid logical path')
    p=Path(value);require(not p.is_absolute() and all(x not in ('','.','..') and ':' not in x and x==x.rstrip(' .') and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',x) for x in value.split('/')),'unsafe logical path');return p

def validate_legacy_manifest(value):
    require(type(value) is dict and set(value)=={'schema','files'},'materialization fields')
    require(value['schema']=='rust-duty-onehand-byte-materialization/v1' and type(value['files']) is list and value['files'],'materialization schema/files')
    seen=set()
    for row in value['files']:
        require(type(row) is dict and set(row)=={'ref','repository_path','destination','sha256','bytes','kind'},'materialization record')
        require(type(row['ref']) is str and re.fullmatch('[0-9a-f]{40}',row['ref']),'immutable full Git commit required')
        relative(row['repository_path']);destination=relative(row['destination']);require(str(destination).casefold() not in seen,'duplicate materialized destination');seen.add(str(destination).casefold())
        require(type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}',row['sha256']),'expected source bytes missing')
        require(type(row['bytes']) is int and 0<=row['bytes']<=128*1024**2,'bounded file size')
        require(row['kind'] in ('original-source','hash-only-reference','original-action-delta','existing-public-baseline','existing-public-canonical'),'unreviewed input kind')
        if row['kind']=='existing-public-baseline':require(row['ref']=='1daee9ff0d250b6ad926dedaab4977663f560406' and row['repository_path']=='assets/authoring/mantle/r3/candidate/aella_mantle_r3.blend' and row['sha256']=='6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79','only exact existing public baseline permitted')
        elif row['kind']=='existing-public-canonical':require(row['repository_path']=='assets/locomotion/asset.vra' and row['sha256']=='d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab','only exact existing public canonical permitted')
        elif row['kind']=='original-action-delta':require(row['sha256']=='3a6a244d560e3688742e03133ce2d6afe065128ef231e37b3b55339abee582c8','original delta differs')
        else:require(destination.suffix.lower() not in ('.blend','.fbx','.vra','.vrs','.vrm','.glb','.npz','.bin','.png','.mp4'),'raw/private media excluded from source materialization')
    return value

def materialize_legacy(value,root,read_blob):
    validate_legacy_manifest(value);root=Path(root);require(root.is_absolute() and not root.exists() and '..' not in root.parts,'fresh absolute destination required')
    for part in (*reversed(root.parents),root):
        if part.exists() or part.is_symlink():
            info=part.lstat();require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'redirected materialization root')
    root.mkdir(parents=True)
    records=[]
    for row in value['files']:
        require(shutil.disk_usage(root).free>=1288490189+row['bytes'],'1.2 GiB floor plus exact source file required')
        raw=read_blob(row['ref'],row['repository_path'],row['bytes']);require(type(raw) is bytes and len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'exact Git source bytes differ')
        target=root/relative(row['destination']);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(raw)
        require(hashlib.sha256(target.read_bytes()).hexdigest()==row['sha256'],'written source differs');records.append(row)
    return {'schema':'rust-duty-onehand-byte-checkout/v1','files':records,'byte_preserving_git_blobs':True,'checkout_filters_used':False}


DISK_FLOOR = 1288490189
V2_SCHEMA = 'rust-duty-onehand-byte-materialization/v2'
TRANSPORT_PREFIX = 'tools/onehand_windows/source-transport-v4/'
CODEC_SHA = 'e00395bb674f78ba6da77a2e8b56f59fd7cda1a3b5d4bf8d0559e44ca1baeea6'
TRANSPORT_MANIFEST_SHA = '294adc658cf108fc8eefce80000fe85c7ed394812ff98f493c60e777a325ea70'


def strict_load(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key'); out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def codec():
    # Bootstrap/source tests still support direct v1 blobs with standard library
    # only. The codec is loaded lazily after the entire pinned package exists.
    root = Path(__file__).absolute().parent
    with (root/'source_transport.py').open('rb') as stream: raw = stream.read(128*1024+1)
    require(len(raw) <= 128*1024 and hashlib.sha256(raw).hexdigest() == CODEC_SHA,
            'exact reviewed bounded codec source required')
    mod = types.ModuleType('_onehand_exact_input_codec')
    mod.__file__ = str(root/'source_transport.py')
    exec(compile(raw, mod.__file__, 'exec'), mod.__dict__)
    return mod


PARTS_CODEC_SHA = '758ff9aec16bf3dbfe7c7799e27268f94e6b05294943aad943aad1e5797aecce'
PARTS_MANIFEST_SHA = '01e836880e04df5211424549f21efd66078d75baa9829dbc50b5b3f8c3f4045e'


def parts_codec():
    path = Path(__file__).absolute().parent/'parts_transport.py'
    with path.open('rb') as stream: raw = stream.read(128*1024+1)
    require(len(raw) <= 128*1024 and hashlib.sha256(raw).hexdigest() == PARTS_CODEC_SHA,
            'exact ordered-parts helper required')
    mod = types.ModuleType('_onehand_exact_parts_codec'); mod.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), mod.__dict__)
    return mod


def canonical_transport_rows():
    mod = codec(); root = Path(__file__).absolute().parent
    value = mod.read_pinned_json(root/'TRANSPORT_MANIFEST.json',TRANSPORT_MANIFEST_SHA,256*1024)
    rows = mod.validate_manifest(value)
    catalog = mod.read_pinned_json(root/'TRANSPORT_PARTS.json',PARTS_MANIFEST_SHA,256*1024)
    return parts_codec().validate_catalog(catalog,rows,TRANSPORT_MANIFEST_SHA)


def validate_manifest(value):
    if type(value) is dict and value.get('schema') == 'rust-duty-onehand-byte-materialization/v1':
        return validate_legacy_manifest(value)
    require(type(value) is dict and set(value) == {'schema','files'}
            and value['schema'] == V2_SCHEMA and type(value['files']) is list and value['files'],
            'completed input materialization fields/schema differ')
    expected = {r['canonical']['path']: r for r in canonical_transport_rows()}
    compressed = set(); destinations = set(); git_sources = set(); parts = parts_codec()
    for row in value['files']:
        gzip = type(row) is dict and row.get('encoding') == 'gzip-single-member'
        fields = {'destination','kind','canonical','git','encoding'} | ({'transport'} if gzip else set())
        require(type(row) is dict and set(row) == fields, 'explicit canonical, transport and Git identities required')
        destination = row['destination']; relative(destination)
        require(destination.casefold() not in destinations, 'duplicate materialized destination')
        destinations.add(destination.casefold())
        require(not destination.casefold().startswith('.encoded-transport/') and destination.casefold() != '.encoded-transport',
                'reserved encoded transport path')
        c = row['canonical']; g = row['git']
        require(type(c) is dict and set(c) == {'sha256','bytes'}, 'canonical identity fields')
        if gzip:
            require(destination in expected and type(g) is dict and set(g) == {'parts'}, 'only fixed gzip Git parts permitted')
            e = expected[destination]; parts.validate_git_parts(g['parts'],e)
            require(row['kind'] == e['kind'] and c == {k:e['canonical'][k] for k in ('sha256','bytes')}, 'fixed canonical raw identity differs')
            require(row['transport'] == {'manifest_repository_path':parts.CATALOG_PATH,**{k:e['reconstructed'][k] for k in ('sha256','bytes')}},
                    'fixed reconstructed gzip identity differs')
            compressed.add(destination); inputs = g['parts']
        else:
            require(row['encoding'] == 'identity', 'unsupported transport encoding')
            require(type(g) is dict and set(g) == {'ref','repository_path','sha256','bytes','blob_sha1'}, 'Git identity fields')
            legacy = {'ref':g['ref'],'repository_path':g['repository_path'],'destination':destination,
                      'sha256':c.get('sha256'),'bytes':c.get('bytes'),'kind':row['kind']}
            validate_legacy_manifest({'schema':'rust-duty-onehand-byte-materialization/v1','files':[legacy]})
            require(type(g['blob_sha1']) is str and re.fullmatch('[0-9a-f]{40}',g['blob_sha1']), 'exact Git blob identity required')
            require(c == {k:g[k] for k in ('sha256','bytes')}, 'identity transport and canonical bytes differ')
            require(destination not in expected, 'complete references require explicit lossless transport')
            inputs = [g]
        for item in inputs:
            key = (item['ref'],item['repository_path'])
            require(key not in git_sources, 'duplicated Git input source'); git_sources.add(key)
    require(compressed == set(expected), 'all 38 lossless canonical inputs required')
    for name in destinations:
        require(not any('/'.join(name.split('/')[:i]) in destinations for i in range(1,len(name.split('/')))),
                'materialization file/directory collision')
    return value


def materialize(value,root,read_blob):
    validate_manifest(value)
    if value['schema'] == 'rust-duty-onehand-byte-materialization/v1':
        return materialize_legacy(value,root,read_blob)
    mod = codec(); parts = parts_codec(); root = Path(root)
    expected = {r['canonical']['path']: r for r in canonical_transport_rows()}
    require(root.is_absolute() and not root.exists() and '..' not in root.parts, 'fresh absolute destination required')
    root = mod.ordinary(root,False); parent = root.parent
    while not parent.exists():parent = parent.parent
    reserve = sum(r['canonical']['bytes'] + (r['transport']['bytes'] if r['encoding'] != 'identity' else 0) for r in value['files'])
    require(shutil.disk_usage(parent).free >= DISK_FLOOR+reserve, 'complete decoded and encoded inventory plus disk floor required')
    root.mkdir(parents=True); records = []; encoded_records = []
    for i,row in enumerate(value['files']):
        g = row['git']; c = row['canonical']; transport = row['encoding'] != 'identity'
        require(shutil.disk_usage(root).free >= DISK_FLOOR+c['bytes']+(row['transport']['bytes'] if transport else 0), 'disk floor')
        target = root/relative(row['destination']); target.parent.mkdir(parents=True,exist_ok=True)
        if transport:
            encoded = root/'.encoded-transport'/f'{i:04d}.gz'
            reconstructed = parts.reconstruct(g['parts'],expected[row['destination']],encoded,read_blob)
            with target.open('xb') as stream:mod.decode_verified(encoded,reconstructed,c,stream.write)
            encoded_records.append({'path':encoded.relative_to(root).as_posix(),'reconstructed':reconstructed,'git_parts':g['parts']})
            # No single Git blob/ref ever names the reconstructed gzip or raw
            # decoded file. Part refs live only in the explicit Git inventory.
            records.append({'ref':None,'repository_path':None,'destination':row['destination'],
                            'kind':row['kind'],**c,'encoding':row['encoding'],
                            'canonical':c,'transport':row['transport'],'git':g})
        else:
            raw = read_blob(g['ref'],g['repository_path'],g['bytes'])
            require(type(raw) is bytes and len(raw) == g['bytes'] and hashlib.sha256(raw).hexdigest() == g['sha256'], 'exact Git bytes differ')
            require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == g['blob_sha1'], 'exact Git blob identity differs')
            with target.open('xb') as stream:stream.write(raw)
            records.append({'ref':g['ref'],'repository_path':g['repository_path'],
                            'destination':row['destination'],'kind':row['kind'],**c,
                            'encoding':row['encoding'],'canonical':c,'git':g})
        require(mod.fingerprint(target,128*1024**2) == c, 'written canonical bytes differ')
    return {'schema':'rust-duty-onehand-byte-checkout/v2','files':records,
            'encoded_transport_files':encoded_records,'byte_preserving_git_blobs':False,
            'canonical_bytes_verified':True,'checkout_filters_used':False,'native_admission':False}

def git_blob_reader(git,repository):
    verified=set()
    def read(ref,path,expected_size):
        require(type(ref) is str and re.fullmatch('[0-9a-f]{40}',ref),'immutable full Git commit required')
        if ref not in verified:
            kind=subprocess.run([git,'-C',str(repository),'cat-file','-t',ref],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
            require(kind.stdout.strip()==b'commit','actual Git commit object required; tree/blob/tag rejected');verified.add(ref)
        size=subprocess.run([git,'-C',str(repository),'cat-file','-s',ref+':'+path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
        require(size.stdout.strip()==str(expected_size).encode(),'Git blob size differs before materialization')
        value=subprocess.run([git,'-C',str(repository),'cat-file','blob',ref+':'+path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True);return value.stdout
    return read

def main():
    p=argparse.ArgumentParser();p.add_argument('--git',required=True);p.add_argument('--repository',required=True);p.add_argument('--manifest',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--output',required=True);p.add_argument('--receipt',required=True);a=p.parse_args()
    with Path(a.manifest).open('rb') as stream:raw=stream.read(8*1024**2+1)
    require(len(raw)<=8*1024**2,'manifest byte cap');require(hashlib.sha256(raw).hexdigest()==a.manifest_sha256,'reviewed materialization manifest differs')
    result=materialize(strict_load(raw),Path(a.output),git_blob_reader(a.git,a.repository))
    with Path(a.receipt).open('xb') as f:f.write((json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode())
if __name__=='__main__':main()
