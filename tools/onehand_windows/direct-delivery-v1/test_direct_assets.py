"""Pure-Python regression checks; no Blender, Rust executable or capture is run."""
from __future__ import annotations
import ast
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import types
import unittest
import zlib

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE / 'tools'))
import vrview
import vrskin
import vrpack

# The narrow recovered source view lacks these two ordinary repository modules.
# Real checkouts use the originals. In this isolated test view only, the offset
# scanner and opaque patch constant are fixture dependencies, not production code.
if importlib.util.find_spec('merge_walk_clip') is None:
    def fixture_clip_offset(data):
        vrview.decode_vra(data)
        offset = 24 + 8
        def u32():
            nonlocal offset
            value = struct.unpack_from('<I', data, offset)[0]; offset += 4
            return value
        def name():
            nonlocal offset
            n = struct.unpack_from('<H', data, offset)[0]; offset += 2 + n
        for _ in range(u32()):
            name(); offset += 4
        for _ in range(u32()):
            name(); count = u32(); offset += count * 4 + 64
        return offset
    sys.modules['merge_walk_clip'] = types.SimpleNamespace(clip_offset=fixture_clip_offset)
if importlib.util.find_spec('jump_landing_patch') is None:
    sys.modules['jump_landing_patch'] = types.SimpleNamespace(
        PATCH_PROVENANCE={'test_fixture': 'unchanged Action metadata'})
from jump_landing_patch import PATCH_PROVENANCE
import package_game as pkg
from direct_game_asset_plan import generator_plan, stage_command


def digest(blob):
    return {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}


def put_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def transport(folder, files, names):
    result = {}
    for name in names:
        blob = files[name]; packed = gzip.compress(blob, mtime=0)
        (folder / (name + '.gz')).write_bytes(packed)
        result[name] = {'file': name + '.gz', 'encoding': 'gzip', **digest(packed),
                        'decoded_bytes': len(blob), 'decoded_sha256': digest(blob)['sha256']}
    return result


def make_fixture(root):
    identity = (1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)
    bones = [(f'bone{i}', i - 1) for i in range(72)]
    vertex = (0.,0.,0.,0.,0.,1.,0.,0.)
    mesh = ((1.,1.,1.,1.,0.,1.), 0, 0, b'', [vertex] * 3, [0,1,2])
    skin_vertex = vertex + (0,) * 8 + (1.,) + (0.,) * 7
    skin_mesh = (*mesh[:4], [skin_vertex] * 3, mesh[-1])
    vrs = vrskin.encode_vrs([(n,p,identity,identity) for n,p in bones], [skin_mesh])
    vrm = vrpack.encode_vrm([mesh, mesh])
    actors = [{'name': n, 'meshes': [i], 'inverse_rest_global': identity}
              for i,n in enumerate(('hk416_weapon', 'hk416_magazine'))]
    trs = (0.,0.,0.,0.,0.,0.,1.,1.,1.,1.)
    def clip(name, loop=False, end=1, subdivisions=1):
        duration = (end - 1) / 60
        count = (end - 1) * subdivisions + 1
        return {'name': name, 'loop': loop, 'frames': [
            {'time': i * duration / (count - 1) if count > 1 else 0.,
             'bones': [trs] * 72, 'actors': [trs] * 2, 'visible': [1,1]}
            for i in range(count)]}
    canonical = [clip(n) for n in pkg.CLIPS]
    def write_pack(kind, clips, manifest, gz):
        folder = root / 'assets' / kind; folder.mkdir(parents=True)
        files = {'asset.vra': vrview.encode_vra(bones, actors, clips, vrs, vrm),
                 'asset.vrs': vrs, 'asset.vrm': vrm}
        for name, data in files.items(): (folder / name).write_bytes(data)
        manifest.update(files={n: digest(b) for n,b in files.items()},
                        clip_count=len(clips), clip_names=[c['name'] for c in clips])
        manifest['repository_transport'] = transport(folder, files, gz)
        put_json(folder / 'manifest.json', manifest)
        (folder / 'README.md').write_text('Fixture only.\n')
        return manifest
    base = write_pack('locomotion', canonical,
                      {'schema': 'rust-duty-locomotion-distribution/v1'}, ['asset.vrs'])
    walk_clips = canonical + [clip('normal_walk_r1', True, 45)]
    walk_source = {'file': 'assets/authoring/locomotion/locomotion.blend', 'bytes': 1,
                   'sha256': '1' * 64, 'fbx': {'sha256': '2' * 64}, 'action': 'normal_walk_r1',
                   'frame_start': 1, 'frame_end': 45, 'fps': 60}
    walk = write_pack('walk', walk_clips,
        {'schema': 'rust-duty-authored-walk-distribution/v1', 'source': walk_source,
         'walk_clip': 'normal_walk_r1', 'loop': True}, ['asset.vrs'])
    def conversion(source, name, end):
        return {'authoring_master_sha256': source['sha256'],
                'source_fbx_sha256': source['fbx']['sha256'], 'native_fps': [60,1],
                'source_take': name, 'native_crop': [0,end-1], 'imported_frame_offset': 0,
                'timing_policy': {'subdivisions': 8, 'samples': (end - 1) * 8 + 1}}
    put_json(root / 'assets/walk/conversion.json', conversion(walk_source, 'normal_walk_r1', 45))
    kinds = [
        ('ads', pkg.ADS_CLIPS, [False,True,False], [16,61,16], list(pkg.ADS_CLIPS),
         'assets/authoring/ads/ads.blend', '3' * 64, 'v1'),
        ('directional', pkg.DIRECTIONAL_CLIPS, [True]*4, pkg.DIRECTIONAL_ENDS,
         pkg.DIRECTIONAL_ACTIONS, pkg.DIRECTIONAL_SOURCE, pkg.DIRECTIONAL_SOURCE_SHA256, 'v2'),
        ('jump', pkg.JUMP_CLIPS, [False]*3, [12,24,29],
         ['jump_takeoff_r7','jump_air_r7','jump_land_r8_ease_candidate'],
         'assets/authoring/jump/halcyon_jump.blend',
         'a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b', 'v2')]
    for kind, names, loops, ends, actions, source_file, sha, version in kinds:
        source = {'file': source_file, 'bytes': 1, 'sha256': sha, 'fps': 60,
                  'bake_hz': 480, 'fbx': {'sha256': '4' * 64}}
        if kind == 'jump': source['action_patch'] = PATCH_PROVENANCE
        manifest = {'schema': 'rust-duty-authored-' + kind + '-distribution/' + version,
            'source': source, kind + '_clips': [
                {'name':n,'loop':loop,'action':a,'frame_start':1,'frame_end':end,'duration':(end-1)/60}
                for n,loop,end,a in zip(names,loops,ends,actions)],
            'preservation': {'original_walk_vra_sha256': walk['files']['asset.vra']['sha256'],
                             'clip_payloads_byte_identical':44}}
        write_pack(kind, walk_clips + [clip(n,loop,end,8) for n,loop,end in zip(names,loops,ends)],
                   manifest, ['asset.vra','asset.vrs'])
        for n,end in zip(names,ends):
            put_json(root / 'assets' / kind / f'conversion-{n}.json', conversion(source,n,end))
    source = {'schema': 'rust-duty-blender-source/v1', 'sha256': '5'*64,
              'action': 'reload_fixture', 'native_range': [0,1], 'clip': 'reload_fixture'}
    manifest = write_pack('reload', [clip('reload_fixture', False, 2)],
        {'authoring_master_sha256': source['sha256'], 'source_fbx_sha256': '6'*64,
         'native_crop': [0,1]}, [])
    put_json(root / 'assets/reload/source.json', source)
    put_json(root / 'assets/reload/export-manifest.json',
        {'source_sha256': source['sha256'], 'action':source['action'], 'native_requested_range':[0,1],
         'action_inventory': ['reload_fixture'], 'files': {'current-full-wip.fbx':{'sha256':'6'*64}}})
    text = 'regular_walk.asset=directional/asset.vra\nregular_walk.clip=normal_walk_r1\n'
    for direction, name in zip(('forward','backward','left','right'),pkg.DIRECTIONAL_CLIPS):
        text += f'regular_walk.direction.{direction}={name}\n'
    text += 'ads.asset=ads/asset.vra\njump.asset=jump/asset.vra\n'
    (root / 'assets/animations.cfg').write_text(text)
    for name in (*pkg.NOTICES, *pkg.RUNTIME_FILES, *pkg.BUILD_FILES, 'docs/ANIMATION_SLOTS.md', 'vector-range.exe'):
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture')


class DirectAssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(dir=HERE)
        cls.root = Path(cls.fixture.name)
        make_fixture(cls.root)

    @classmethod
    def tearDownClass(cls): cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.work = Path(self.temp.name)
        self.root_copy = self.work / 'source'
        shutil.copytree(self.root, self.root_copy)

    def tearDown(self): self.temp.cleanup()

    def test_no_parity_files_required_for_all_packs_and_stage(self):
        root = self.root_copy
        self.assertFalse(list(root.rglob('*parity*')))
        pkg.verify(root)
        result = pkg.verify_generated(root)
        self.assertEqual(result['selected_packs'], 1)
        staged = self.work / 'stage'
        pkg.stage(root, 'vector-range.exe', staged, require_generated=True)
        self.assertEqual((staged/'settings.cfg').read_bytes(), (root/'settings.cfg').read_bytes())
        for name in pkg.RUNTIME_FILES:
            self.assertEqual((staged/name).read_bytes(),(root/name).read_bytes())
        self.assertFalse(list(staged.rglob('*parity*')))
        pkg.verify_generated(staged)

    def test_failed_and_malformed_parity_never_gate_packaging(self):
        root = self.root_copy
        for folder in ('reload','walk','ads','directional','jump'):
            for name in ('parity.json','runtime-seams.json',
                         *(f'parity-{c}.json' for c in (*pkg.ADS_CLIPS,*pkg.DIRECTIONAL_CLIPS,*pkg.JUMP_CLIPS))):
                (root/'assets'/folder/name).write_text('{invalid legacy report' if 'seams' in name else '{"passed":false}')
            path = root/'assets'/folder/'manifest.json'; data=json.loads(path.read_text())
            data['validation'] = {'passed':False,'backend':'Rust CPU sampler'}; put_json(path,data)
        result = pkg.stage(root,'vector-range.exe',self.work/'stage', require_generated=True)
        self.assertGreater(result['files_staged'],0)
        self.assertFalse(list((self.work/'stage').rglob('*parity*')))
        self.assertFalse(list((self.work/'stage').rglob('*seams*')))

    def test_bad_reload_format_with_matching_hash_still_fails(self):
        root = self.root_copy; folder=root/'assets/reload'; file=folder/'asset.vra'
        blob=bytearray(file.read_bytes());blob[0]=0;file.write_bytes(blob)
        manifest=json.loads((folder/'manifest.json').read_text());manifest['files']['asset.vra']=digest(blob)
        put_json(folder/'manifest.json',manifest)
        with self.assertRaisesRegex(vrpack.AssetError,'magic/version'):
            pkg.stage(root, 'vector-range.exe', self.work/'stage', require_generated=True)
        self.assertFalse((self.work/'stage').exists())

    def test_walk_finish_produces_distribution_without_parity(self):
        import build_walk_assets
        root=self.root_copy;source=root/'assets/authoring/locomotion';source.mkdir(parents=True)
        (source/'locomotion.blend').write_bytes(b'synthetic authoring metadata fixture')
        put_json(source/'export_config.json',{'source_fps':60,'source_takes':[
            {'name':'normal_walk_r1','action':'normal_walk_r1','frame_start':1,'frame_end':45,'loop':True}]})
        exported=self.work/'fbx';exported.mkdir();(exported/'locomotion.fbx').write_bytes(b'fixture')
        imported=self.work/'imported';imported.mkdir()
        put_json(imported/'manifest.json',{
            'authoring_master_sha256':digest((source/'locomotion.blend').read_bytes())['sha256'],
            'source_fbx_sha256':digest((exported/'locomotion.fbx').read_bytes())['sha256'],
            'native_fps':[60,1],'source_take':'normal_walk_r1'})
        output=self.work/'new-walk'
        build_walk_assets.finish(root,source,exported,imported,root/'assets/walk',output)
        self.assertFalse((output/'parity.json').exists())
        self.assertEqual(pkg.verify_walk(root,output)['clip'],'normal_walk_r1')
        self.assertNotIn('validation',json.loads((output/'manifest.json').read_text()))

    def test_source_hash_and_native_clock_still_checked(self):
        root = self.root_copy;path=root/'assets/walk/conversion.json'
        value=json.loads(path.read_text());value['native_fps']=[30,1];put_json(path,value)
        with self.assertRaisesRegex(ValueError,'conversion/source'):
            pkg.verify_walk(root)

    def test_companion_hash_corruption_still_fails(self):
        root = self.root_copy;file=root/'assets/reload/asset.vrm';file.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'companion hash'):
            pkg.verify_generated_pack(root,pkg.GENERATED_DIR)

    def test_absolute_generated_directory_is_supported(self):
        root=self.root_copy;output=self.work/'generated';shutil.copytree(root/'assets/reload',output)
        self.assertEqual(pkg.verify_generated_pack(root,output)['clip'],'reload_fixture')

    def test_explicit_pack_symlink_rejected(self):
        link=self.work/'linked';link.symlink_to(self.root_copy/'assets/reload',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            pkg.verify_generated_pack(self.root_copy,link)

    def test_no_sampler_or_capture_in_generation_plan(self):
        jobs=generator_plan('C:/game','C:/job/base','python','blender')
        self.assertEqual(len(jobs),12)
        self.assertEqual([j['stage']['kind'] for j in jobs if 'stage' in j],
                         ['reload','walk','ads','directional','jump'])
        for job in jobs:
            self.assertFalse(any(term in ' '.join(job['argv']) for term in
                                 ('sampler','parity','capture','cargo','verify_jump_seams')))
        self.assertEqual(stage_command('root','vector-range.exe','output')[-1],'--require-generated')

    def test_active_builders_have_no_numerical_admission(self):
        for path in (HERE/'tools').glob('build_*assets.py'):
            source=path.read_text();ast.parse(source)
            self.assertNotIn('--sampler',source)
            self.assertNotIn('--verify-sampler',source)
            self.assertNotIn('parity',source)
            self.assertNotIn('verify_jump_seams',source)
        self.assertIn("'--subdivisions', '8', '--fps', '60'",(HERE/'tools/build_jump_assets.py').read_text())
        self.assertIn("'--native-start', '0', '--native-end', take['frame_end'] - 1",(HERE/'tools/build_jump_assets.py').read_text())

    def test_optional_high_low_prone_references_are_copied_unchanged(self):
        root = self.root_copy
        lines = []
        files = []
        for slot, folder in [('high_mantle','onehand'),('low_vault','low_vault'),('prone_entry','prone_entry')]:
            lines += [f'{slot}.asset={folder}/asset.vra']
            for suffix in ('vra','vrs','vrm'):
                relative = Path('assets')/folder/('asset.'+suffix)
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(root/'assets/reload'/('asset.'+suffix),target);files.append(relative)
            receipt = 'asset.prone-pair.json' if slot=='prone_entry' else 'runtime-receipt.json'
            lines.append(f'{slot}.receipt={folder}/{receipt}')
            relative = Path('assets')/folder/receipt
            # Deliberately failed legacy evidence inside copied metadata is not admission.
            put_json(root/relative,{'passed':False,'original_metadata':'unchanged'});files.append(relative)
        lines.append('prone_entry.camera=prone_entry/asset.prone-camera.json')
        camera=Path('assets/prone_entry/asset.prone-camera.json');put_json(root/camera,{'frames':[]});files.append(camera)
        cfg=root/'assets/animations.cfg'
        cfg.write_text(cfg.read_text()+'\n'.join(lines)+'\n')
        before=cfg.read_bytes()
        pkg.materialize(root,True,True,True,True)
        self.assertEqual(cfg.read_bytes(),before)
        output=self.work/'optional-stage'
        pkg.stage(root,'vector-range.exe',output,require_generated=True)
        self.assertEqual((output/'assets/animations.cfg').read_bytes(),before)
        for relative in files:
            self.assertEqual((root/relative).read_bytes(),(output/relative).read_bytes())

    def test_optional_paths_cannot_escape_or_follow_symlinks(self):
        cfg=self.root_copy/'assets/animations.cfg';original=cfg.read_text()
        for value in ('../private.bin','/private.bin','C:/private.bin','x\\private.bin'):
            cfg.write_text(original+'high_mantle.receipt='+value+'\n')
            with self.assertRaisesRegex(ValueError,'unsafe optional'):
                pkg.optional_runtime_files(self.root_copy)
        linked=self.root_copy/'assets/unsafe';linked.symlink_to(self.work,target_is_directory=True)
        cfg.write_text(original+'high_mantle.receipt=unsafe/receipt.json\n')
        with self.assertRaisesRegex(ValueError,'symlink'):
            pkg.optional_runtime_files(self.root_copy)

    def test_update_preserves_user_settings_exclusion(self):
        pkg.stage(self.root_copy,'vector-range.exe',self.work/'update',update=True,require_generated=True)
        self.assertFalse((self.work/'update/settings.cfg').exists())
        self.assertTrue((self.work/'update/ui/theme.css').is_file())


if __name__=='__main__': unittest.main()
