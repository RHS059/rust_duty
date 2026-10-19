import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import canonical_runtime_package as package


class CanonicalPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.overlay, self.game = [self.base / n for n in ('root', 'overlay', 'game')]
        for p in (self.root, self.overlay, self.game): p.mkdir()
        self.mapping = {'clips': [{'id':'ready','name':'ready','bundle':'locomotion','loop':False}], 'excluded': {'special':'preserved'}}
        self.write(self.root, package.SOURCE, b'canonical-source')
        self.write(self.root, package.MAP, json.dumps(self.mapping).encode())
        self.write(self.root, 'assets/animations.cfg', b'existing binding')
        self.write(self.game, 'assets/animations.cfg', b'existing binding')
        self.write(self.game, 'assets/special/camera.bin', b'keep exact')
        self.write(self.game, 'vector-range.exe', b'executable')
        self.write(self.game, 'assets/locomotion/manifest.json', b'old provenance')
        files = {'assets/animations.cfg': b'existing binding', 'conversion/ready/manifest.json': b'{"source":"new"}'}
        baseline = {}; preserved = {}
        for suffix in ('vra','vrs','vrm'):
            name = 'assets/locomotion/asset.' + suffix
            raw = ('old-' + suffix).encode()
            self.write(self.game, name, raw)
            baseline[name] = package.digest(raw)
            files[name] = b'new-animation' if suffix == 'vra' else raw
            if suffix != 'vra': preserved[name] = package.digest(raw)
        for name, raw in files.items(): self.write(self.overlay, name, raw)
        self.receipt = {'schema':package.SCHEMA,'source':package.SOURCE,
                        'source_sha256':package.digest(b'canonical-source')['sha256'],
                        'runtime_map_sha256':package.digest((self.root/package.MAP).read_bytes())['sha256'],
                        'mapped_clips':self.mapping['clips'], 'preserved_exports':self.mapping['excluded'],
                        'files':{n:package.digest(v) for n,v in files.items()},
                        'baseline_files':baseline,'preserved_companions':preserved}
        self.save()
        module = types.SimpleNamespace(BUNDLES=('locomotion',), load_map=lambda path: json.loads(path.read_text()))
        self.runtime_patch = patch.dict('sys.modules', {'nla_export.runtime': module})
        self.runtime_patch.start(); self.addCleanup(self.runtime_patch.stop)
        self.decoder = patch.object(package.vrview, 'decode_vra', return_value={'clips':[{'name':'ready','loop':False}]})
        self.decoder.start(); self.addCleanup(self.decoder.stop)

    def write(self, root, name, data):
        p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)

    def save(self):
        self.write(self.overlay, 'runtime-manifest.json', json.dumps(self.receipt).encode())

    def test_apply_preserves_unmapped_files_and_replaces_provenance(self):
        report = package.apply(self.root, self.overlay, self.game)
        self.assertEqual(report['mapped_clips'], 1)
        self.assertEqual((self.game/'assets/locomotion/asset.vra').read_bytes(), b'new-animation')
        self.assertEqual((self.game/'assets/special/camera.bin').read_bytes(), b'keep exact')
        self.assertEqual((self.game/'vector-range.exe').read_bytes(), b'executable')
        self.assertFalse((self.game/'assets/locomotion/manifest.json').exists())
        self.assertTrue((self.game/'CANONICAL_RUNTIME.json').is_file())
        self.assertTrue((self.game/'canonical-runtime/conversion/ready/manifest.json').is_file())
        installed=json.loads((self.game/'CANONICAL_RUNTIME.json').read_text())
        self.assertEqual(installed['schema'],'rust-duty-canonical-runtime-package/v1')
        for name,pin in installed['files'].items():
            self.assertEqual(package.digest((self.game/name).read_bytes()),pin)

    def test_corrupt_overlay_rejected_without_mutation(self):
        self.write(self.overlay,'assets/locomotion/asset.vra',b'corrupt')
        with self.assertRaisesRegex(ValueError,'bytes differ'): package.apply(self.root,self.overlay,self.game)
        self.assertEqual((self.game/'assets/locomotion/asset.vra').read_bytes(), b'old-vra')

    def test_wrong_source_rejected(self):
        self.write(self.root,package.SOURCE,b'other')
        with self.assertRaisesRegex(ValueError,'source hash'): package.apply(self.root,self.overlay,self.game)

    def test_extra_path_rejected(self):
        self.receipt['files']['../escape'] = package.digest(b'bad'); self.save()
        with self.assertRaisesRegex(ValueError,'inventory'): package.apply(self.root,self.overlay,self.game)

    def test_changed_baseline_rejected(self):
        self.write(self.game,'assets/locomotion/asset.vra',b'other')
        with self.assertRaisesRegex(ValueError,'baseline differs'): package.apply(self.root,self.overlay,self.game)

    def test_changed_binding_rejected_even_with_updated_hash(self):
        self.write(self.overlay,'assets/animations.cfg',b'changed')
        self.receipt['files']['assets/animations.cfg'] = package.digest(b'changed'); self.save()
        with self.assertRaisesRegex(ValueError,'bindings'): package.apply(self.root,self.overlay,self.game)

    def test_invalid_runtime_format_rejected(self):
        with patch.object(package.vrview,'decode_vra',side_effect=ValueError('invalid format')):
            with self.assertRaisesRegex(ValueError,'invalid format'): package.apply(self.root,self.overlay,self.game)

    def test_clip_binding_change_rejected(self):
        with patch.object(package.vrview,'decode_vra',side_effect=[{'clips':[{'name':'other','loop':False}]},{'clips':[{'name':'ready','loop':False}]}]):
            with self.assertRaisesRegex(ValueError,'clip order'): package.apply(self.root,self.overlay,self.game)

    def test_destination_symlink_rejected(self):
        link=self.game/'link'
        try: link.symlink_to(self.root, target_is_directory=True)
        except OSError: self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(ValueError,'symlink'): package.apply(self.root,self.overlay,self.game)

    def test_preserved_geometry_cannot_be_rehashed_away(self):
        name='assets/locomotion/asset.vrs'
        self.write(self.overlay,name,b'changed skin')
        self.receipt['files'][name]=package.digest(b'changed skin')
        self.receipt['preserved_companions'][name]=package.digest(b'changed skin')
        self.save()
        with self.assertRaisesRegex(ValueError,'preserved geometry'): package.apply(self.root,self.overlay,self.game)

    def test_workflow_uses_same_run_and_updates_both_distributions(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/build.yml').read_text()
        self.assertIn('needs: [changes, canonical-runtime]',workflow)
        self.assertIn('uses: ./.github/workflows/canonical-weapon-nla.yml',workflow)
        self.assertIn('name: canonical-weapon-runtime',workflow)
        self.assertIn('--destination dist/game',workflow)
        self.assertIn('--destination preflight/payload',workflow)
        self.assertNotIn('stage --root dist/game',workflow)
        step=workflow.split("      - name: Download this run's canonical runtime overlay")[1].split('      - name:',1)[0]
        self.assertNotIn('run-id:',step)
        self.assertNotIn('github-token:',step)

    def test_conversion_receipt_tampering_rejected(self):
        self.write(self.overlay,'conversion/ready/manifest.json',b'changed')
        with self.assertRaisesRegex(ValueError,'bytes differ'): package.apply(self.root,self.overlay,self.game)

if __name__ == '__main__': unittest.main()
