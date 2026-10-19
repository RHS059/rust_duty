"""Convert explicitly mapped canonical FBXs into a game-runtime assets overlay.

This does not alter the authoring BLEND, checkout assets, or gameplay bindings.
Specialized camera bundles and unbound exports are explicitly left untouched.
"""
from __future__ import annotations
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import struct
import zlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vrpack
import vrview
from merge_walk_clip import BASIS, clip_offset

BUNDLES = ('locomotion', 'walk', 'directional', 'ads', 'jump', 'reload')
INHERITS = {'locomotion': ('locomotion',), 'walk': ('locomotion', 'walk'),
            'directional': ('locomotion', 'walk', 'directional'),
            'ads': ('locomotion', 'walk', 'ads'), 'jump': ('locomotion', 'walk', 'jump'), 'reload': ('reload',)}


def digest(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def load_map(path):
    mapping = json.loads(path.read_text())
    if mapping.get('schema') != 'rust-duty-canonical-runtime-map/v1':
        raise ValueError('unsupported runtime map')
    ids = set(); names = set()
    for c in mapping['clips']:
        if (not re.fullmatch('[a-z0-9_]+', c['id']) or c['id'] in ids
                or not re.fullmatch('[a-z0-9_]+', c['name']) or c['name'] in names
                or c['bundle'] not in BUNDLES or type(c['loop']) is not bool):
            raise ValueError('invalid or duplicate runtime mapping')
        ids.add(c['id']); names.add(c['name'])
    if ids & mapping['excluded'].keys():
        raise ValueError('mapped/excluded overlap')
    return mapping


def plan(mapping, manifest):
    if manifest.get('schema') != 'rust-duty-weapon-fbx/v1':
        raise ValueError('unsupported FBX manifest')
    clips = {c['id']: c for c in manifest['clips']}
    if len(clips) != len(manifest['clips']):
        raise ValueError('duplicate FBX clip')
    expected = {c['id'] for c in mapping['clips']} | mapping['excluded'].keys()
    if expected != clips.keys():
        raise ValueError('every export must have an explicit runtime mapping or exclusion')
    result = []
    for row in mapping['clips']:
        c = clips[row['id']]
        if c['file'] != c['id']+'.fbx' or c['take'] != c['id']:
            raise ValueError('unsafe or mismatched FBX filename/take')
        required_actors={'hk416_weapon','hk416_magazine'}
        if row['bundle']=='reload': required_actors.add('hk416_magazine_outgoing')
        if not required_actors <= set(c.get('objects', [])):
            raise ValueError('missing required runtime actor: '+c['id'])
        length = c['frame_end'] - c['frame_start']
        if type(length) not in (int, float) or int(length) != length or length < 0:
            raise ValueError('invalid source frame range')
        fps = Fraction(str(c['fps'])) / Fraction(str(c.get('fps_base', 1)))
        if fps <= 0:
            raise ValueError('invalid FPS')
        result.append({**row, 'export': c, 'end': int(length), 'fps': str(fps)})
    return result


def read_asset(root, bundle, suffix):
    path = root/'assets'/bundle/('asset.'+suffix)
    if path.is_file():
        return path.read_bytes()
    return gzip.decompress(path.with_suffix(path.suffix+'.gz').read_bytes())


def replace_clips(base, replacements, vrs, vrm):
    """Replace named clips, keeping baseline order, geometry and all unselected clips.

    Ordinary FBX imports use Y-up rigid vertices; canonical locomotion actors use
    Blender-local vertices. Apply the existing merge_walk_clip basis once.
    Reload is emitted with its own converted geometry instead of this function.
    """
    original = vrview.decode_vra(base, vrs=vrs, vrm=vrm)
    available = {c['name'] for c in original['clips']}
    if not replacements.keys() <= available:
        raise ValueError('replacement names must already exist in this bundle')
    cooked = {}
    for name, incoming in replacements.items():
        new = vrview.decode_vra(incoming)
        matches = [c for c in new['clips'] if c['name'] == name]
        if len(matches) != 1:
            raise ValueError('missing or duplicate incoming clip')
        names = [n for n, _ in new['bones']]
        if set(names) != {n for n, _ in original['bones']}:
            raise ValueError('skeleton names differ')
        for n, p in original['bones']:
            j = names.index(n); q = new['bones'][j][1]
            if (original['bones'][p][0] if p >= 0 else None) != (names[q] if q >= 0 else None):
                raise ValueError('skeleton parents differ')
        actors = [a['name'] for a in new['actors']]
        if set(actors) != {a['name'] for a in original['actors']}:
            raise ValueError('actor names differ')
        order = [names.index(n) for n, _ in original['bones']]
        actor_order = [actors.index(a['name']) for a in original['actors']]
        clip = copy.deepcopy(matches[0])
        old = next(c for c in original['clips'] if c['name'] == name)
        if clip['loop'] != old['loop']:
            raise ValueError('mapped loop setting differs from current runtime')
        for frame in clip['frames']:
            frame['bones'] = [frame['bones'][i] for i in order]
            frame['actors'] = [vrview.decompose(vrpack.matmul(vrview.matrix(frame['actors'][i]), BASIS)) for i in actor_order]
            frame['visible'] = [frame['visible'][i] for i in actor_order]
        cooked[name] = clip
    offset = clip_offset(base)
    payload = bytearray(base[24:offset+4])
    cursor = offset+4
    for old in original['clips']:
        encoded_old = vrview.encode_vra(original['bones'], original['actors'], [old], vrs, vrm)
        record_length = len(encoded_old)-clip_offset(encoded_old)-4
        if old['name'] in cooked:
            encoded = vrview.encode_vra(original['bones'], original['actors'], [cooked[old['name']]], vrs, vrm)
            payload.extend(encoded[clip_offset(encoded)+4:])
        else:
            payload.extend(base[cursor:cursor+record_length])
        cursor += record_length
    if cursor != len(base):
        raise ValueError('clip record accounting differs')
    return vrview.HEADER.pack(vrview.MAGIC, vrview.VERSION, len(payload), zlib.crc32(payload), 0)+payload


def conversion_command(root, exports, source, manifest, entry, dest, blender):
    c=entry['export']
    command=[blender,'--background','--threads','2','--factory-startup','--disable-autoexec',
             '--python-exit-code','1','--python',str(root/'tools/import_fbx_viewmodel.py'),'--',
             '--fbx',str(exports/c['file']),'--fbx-sha256',c['sha256'],
             '--source-sha256',manifest['source_sha256'],'--material-source',str(source),
             '--skeleton-vra',str(root/'assets/locomotion/asset.vra'),
             '--output',str(dest),'--armature',c['exported_rig'],
             '--actor','hk416_weapon','--actor','hk416_magazine',
             '--native-start','0','--native-end',str(entry['end']),
             '--fps',entry['fps'],'--imported-frame-offset',str(c['frame_start']),'--take',c['take'],
             '--subdivisions','8','--name',entry['name']]
    if entry['loop']: command.append('--loop')
    if entry['bundle']=='reload':
        command.extend(['--actor','hk416_magazine_outgoing'])
    return command


def build(root, exports, output, blender='blender', mapping_path=None, jobs=2):
    if type(jobs) is not int or not 1 <= jobs <= 4:
        raise ValueError('conversion jobs must be between 1 and 4')
    root=root.resolve(); exports=exports.resolve(); output=output.resolve()
    if output.exists():
        raise ValueError('use a fresh output directory')
    mapping=load_map(mapping_path or root/'tools/nla_export/runtime_map.json')
    manifest=json.loads((exports/'manifest.json').read_text())
    entries=plan(mapping, manifest)
    source=root/'assets/authoring/weapon_animations.blend'
    if digest(source.read_bytes())['sha256'] != manifest['source_sha256']:
        raise ValueError('FBX bundle belongs to a different canonical BLEND')
    # Verify all inputs before any conversion, and never discover extra FBXs.
    for entry in entries:
        c=entry['export']
        if digest((exports/c['file']).read_bytes())['sha256'] != c['sha256']:
            raise ValueError('FBX bytes differ: '+c['id'])
    output.mkdir(parents=True)
    converted=output/'conversion'; converted.mkdir()
    def convert(entry):
        dest=converted/entry['id']
        command=conversion_command(root, exports, source, manifest, entry, dest, blender)
        subprocess.run(command,cwd=root,check=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(convert, entries))
    return assemble(root, output, converted, entries, manifest, mapping)


def assemble(root, output, converted, entries, manifest, mapping):
    assets=output/'assets'; assets.mkdir()
    for bundle in BUNDLES:
        dest=assets/bundle; dest.mkdir()
        if bundle=='reload':
            for suffix in ('vra','vrs','vrm'):
                shutil.copyfile(converted/'reload_current_wip'/('asset.'+suffix),dest/('asset.'+suffix))
        else:
            vrs=read_asset(root,bundle,'vrs'); vrm=read_asset(root,bundle,'vrm')
            replacements={e['name']:(converted/e['id']/'asset.vra').read_bytes()
                          for e in entries if e['bundle'] in INHERITS[bundle]}
            data=replace_clips(read_asset(root,bundle,'vra'),replacements,vrs,vrm)
            for suffix,raw in [('vra',data),('vrs',vrs),('vrm',vrm)]:
                (dest/('asset.'+suffix)).write_bytes(raw)
    # Existing bindings, unavailable actions and specialized camera paths stay exact.
    shutil.copyfile(root/'assets/animations.cfg',assets/'animations.cfg')
    receipt={'schema':'rust-duty-canonical-runtime-overlay/v1',
             'source':manifest['source'],'source_sha256':manifest['source_sha256'],
             'runtime_map_sha256':digest((root/'tools/nla_export/runtime_map.json').read_bytes())['sha256'],
             'baseline_files':{str(Path('assets')/bundle/('asset.'+suffix)):digest(read_asset(root,bundle,suffix))
                               for bundle in BUNDLES for suffix in ('vra','vrs','vrm')},
             'preserved_companions':{str(Path('assets')/bundle/('asset.'+suffix)):digest(read_asset(root,bundle,suffix))
                                     for bundle in BUNDLES if bundle != 'reload' for suffix in ('vrs','vrm')},
             'mapped_clips':mapping['clips'],
             'preserved_exports':mapping['excluded'],
             'files':{str(p.relative_to(output)):digest(p.read_bytes()) for p in [*sorted(assets.rglob('*')), *sorted(converted.glob('*/manifest.json'))] if p.is_file()},
             'installation':'Overlay assets on the existing game distribution; specialized bundles are retained. Historical package_game.py contracts are not replaced by this artifact.'}
    (output/'runtime-manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
    # Only small receipts are needed after conversion; avoid shipping 55 duplicate geometries.
    for directory in converted.iterdir():
        for file in directory.iterdir():
            if file.name != 'manifest.json': file.unlink()
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--exports',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--blender',default='blender')
    p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args(); build(a.root,a.exports,a.output,a.blender,jobs=a.jobs)
