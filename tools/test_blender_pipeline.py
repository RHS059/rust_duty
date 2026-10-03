"""Pipeline integrity tests, independent of Blender and private external inputs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import build_blender_assets
import package_game
from test_vrview import fixture
import vrview

ROOT = Path(__file__).resolve().parents[1]


class BlenderPipelineTests(unittest.TestCase):
    def test_committed_source_exact_contract(self):
        base = ROOT / 'assets/source/reload'
        contract = json.loads((base / 'source.json').read_text())
        source = (base / contract['file']).read_bytes()
        self.assertEqual(len(source), contract['bytes'])
        self.assertEqual(hashlib.sha256(source).hexdigest(), contract['sha256'])
        self.assertEqual(contract['native_range'], [0, 156])

    def fixture(self, root):
        folder = root / package_game.GENERATED_DIR
        folder.mkdir(parents=True)
        doc, blob, _ = fixture()
        scene = vrview.Scene(doc, blob)
        vrs, vrm, actors = scene.companions(['gun'])
        bones, gs = scene.sample(0.)
        vra = vrview.encode_vra(scene.skin.bones, actors,
            [{'name': 'reload_current_wip', 'loop': False, 'frames': [
                {'time': 0., 'bones': bones, 'actors': [vrview.decompose(gs[5])], 'visible': [1]}]}], vrs, vrm)
        blobs = {'asset.vra': vra, 'asset.vrs': vrs, 'asset.vrm': vrm}
        for name, data in blobs.items():
            (folder / name).write_bytes(data)
        source = {'schema': 'rust-duty-blender-source/v1', 'sha256': 'source',
                  'action': 'selected', 'clip': 'reload_current_wip', 'native_range': [0, 156]}
        manifest = {'authoring_master_sha256': 'source', 'source_fbx_sha256': 'fbx',
                    'native_crop': [0, 156], 'files': {name: {'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()} for name, data in blobs.items()}}
        exported = {'source_sha256': 'source', 'action': 'selected',
                    'native_requested_range': [0, 156], 'action_inventory': [{'name': 'selected'}],
                    'files': {'current-full-wip.fbx': {'sha256': 'fbx'}, 'source-witnesses.npz': {'sha256': 'witnesses'}}}
        parity = {'passed': True, 'backend': 'Rust CPU sampler',
                  'asset_sha256': manifest['files']['asset.vra']['sha256'],
                  'source_witnesses_sha256': 'witnesses', 'visibility_failures': 0, 'samples': 1}
        for name, value in [('manifest', manifest), ('export-manifest', exported), ('source', source), ('parity', parity)]:
            (folder / (name + '.json')).write_text(json.dumps(value))
        (root / 'assets/animations.cfg').write_text('fixture')
        (root / 'docs').mkdir()
        (root / 'docs/ANIMATION_SLOTS.md').write_text('fixture')
        return folder

    def test_generated_pack_matches_hashes_and_rust_parity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            self.assertEqual(package_game.verify_generated(root)['clip'], 'reload_current_wip')

    def test_generated_corruption_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = self.fixture(root)
            (folder / 'asset.vra').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                package_game.verify_generated(root)

    def test_python_only_or_failed_or_wrong_source_parity_fails(self):
        for field, value in [('backend', 'Python diagnostic only'), ('passed', False),
                             ('source_witnesses_sha256', 'wrong'), ('asset_sha256', 'wrong')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                folder = self.fixture(root)
                path = folder / 'parity.json'
                parity = json.loads(path.read_text())
                parity[field] = value
                path.write_text(json.dumps(parity))
                with self.assertRaisesRegex(ValueError, 'Rust parity'):
                    package_game.verify_generated(root)

    def test_missing_generated_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'missing'):
                package_game.verify_generated(Path(temp))

    def test_all_current_selections_remain_separate(self):
        contract = json.loads((ROOT / 'assets/source/reload/source.json').read_text())
        selected = list(build_blender_assets.selections(contract))
        self.assertEqual([key for key, _ in selected], ['', 'opening', 'reset', 'pickup'])
        self.assertEqual([value['native_range'] for _, value in selected], [[0, 156], [0, 30], [0, 0], [54, 54]])
        self.assertEqual(len({value['action'] for _, value in selected}), 4)

    def test_missing_selected_alternate_blocks_distribution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = self.fixture(root)
            path = folder / 'source.json'
            source = json.loads(path.read_text())
            source['additional_selections'] = [{'id': 'opening', 'action': 'opening'}]
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, 'missing'):
                package_game.verify_generated(root)

    def test_no_blender_call_on_source_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'assets/source/reload'
            folder.mkdir(parents=True)
            (folder / 'source.json').write_text(json.dumps({
                'schema': 'rust-duty-blender-source/v1', 'file': 'current.blend', 'blender': '4.3.2',
                'native_fps': [60000, 1001], 'bytes': 3, 'sha256': 'bad'}))
            (folder / 'current.blend').write_bytes(b'bad')
            with patch('build_blender_assets.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'differs'):
                    build_blender_assets.build('blender', root, root / 'output')
                run.assert_not_called()
