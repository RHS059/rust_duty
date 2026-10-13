from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ResidentAuthoredWorkflowTests(unittest.TestCase):
    def test_original_companions_and_source_bound_actual_loader_runner(self):
        body = (ROOT / '.github/workflows/resident-authored-contract.yml').read_text()
        workflow = yaml.load(body, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'push'})
        self.assertEqual(workflow['on']['push']['branches'], ['aella/wgpu-1080p-diagnostics'])
        paths = set(workflow['on']['push']['paths'])
        self.assertTrue({'examples/resident_authored_contract.rs', 'examples/support/resident_vertex_diagnostic.rs', 'tools/**', 'src/**',
                         '.cargo/**', 'rust-toolchain', 'rust-toolchain.toml'} <= paths)
        for name in ('blender', 'walk', 'ads', 'directional', 'jump'):
            self.assertIn('.github/workflows/' + name + '-assets.yml', paths)
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['env']['PYTHONDONTWRITEBYTECODE'], '1')
        job = workflow['jobs']['authored-resident']
        self.assertEqual(set(job['needs']), {'animation-assets', 'walk-assets', 'ads-assets',
                                           'directional-assets', 'jump-assets'})
        self.assertEqual(job['runs-on'], 'windows-latest')
        self.assertEqual(job['timeout-minutes'], '45')
        steps = job['steps']
        checkout = steps[0]['with']
        self.assertEqual(checkout['persist-credentials'], 'false')
        self.assertEqual(checkout['sparse-checkout'].splitlines(), ['/*', '!/assets/weapons/'])
        install = next(i for i, s in enumerate(steps) if 'pip install Pillow==11.3.0 PyYAML==6.0.3' in s.get('run', ''))
        guards = next(i for i, s in enumerate(steps) if 'python -m unittest' in s.get('run', ''))
        materialize = next(i for i, s in enumerate(steps) if 'package_game.py materialize' in s.get('run', ''))
        run = next(i for i, s in enumerate(steps) if 'run_resident_authored_contract.py --root .' in s.get('run', ''))
        self.assertLess(install, guards)
        self.assertLess(guards, run)
        self.assertLess(materialize, run)
        self.assertEqual(steps[run]['timeout-minutes'], '38')
        self.assertIn('--vertex-probe',steps[run]['run'])
        self.assertIn('--require-generated', steps[materialize]['run'])
        for name in ('reload', 'walk', 'ads', 'directional', 'jump'):
            self.assertTrue(any(s.get('with', {}).get('name') == 'generated-' + name + '-runtime'
                                for s in steps))
        for forbidden in ('continue-on-error', 'run_authored_loader_pair.py', 'git fetch', 'secrets.', 'gh pr merge'):
            self.assertNotIn(forbidden, body)

    def test_original_pixels_and_both_corner_streams_survive_failure(self):
        workflow = yaml.load((ROOT / '.github/workflows/resident-authored-contract.yml').read_text(), Loader=yaml.BaseLoader)
        uploads = [s for s in workflow['jobs']['authored-resident']['steps'] if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(len(uploads), 4)
        self.assertTrue(all(s.get('id') and s.get('if') == 'always()' for s in uploads))
        paths = [s['with']['path'] for s in uploads]
        self.assertIn('evidence/resident-authored/captures/*-cpu.corners.bin', paths)
        self.assertIn('evidence/resident-authored/captures/*-resident.corners.bin', paths)
        self.assertTrue(any('captures/*.png' in p and 'build/**' in p and 'process/**' in p for p in paths))
        self.assertTrue(any('vertex-probe/*.json' in p and 'captures/*.png' in p for p in paths))
        source = (ROOT / 'examples/resident_authored_contract.rs').read_text()
        self.assertIn('fixture(&manifest, None)', source)
        self.assertIn('fixture(&manifest, Some(&renderer))', source)
        self.assertIn('renderer.supports_resident_meshes()', source)
        self.assertIn('result.resident.draws == expected', source)
        self.assertLess(source.index('&output.join("report.json")'), source.index('require(\n        all_pass'))
        self.assertLess(source.index('&output.join("report.json")'),source.index('vertex_diagnostic::run('))
        self.assertIn('probe_errors.push',source)


    def test_skin_stage_diagnostic_retains_original_gate_and_explicit_input_scope(self):
        source=(ROOT/'examples/resident_authored_contract.rs').read_text()
        self.assertIn('rust-duty-resident-vertex-probe-result/v2',source)
        workflow=(ROOT/'.github/workflows/resident-authored-contract.yml').read_text()
        self.assertIn('test_resident_vertex_probe test_resident_skin_probe',workflow)
        self.assertLess(source.index('&output.join("report.json")'),source.index('vertex_diagnostic::run('))
        diagnostic=(ROOT/'examples/support/resident_vertex_diagnostic.rs').read_text()
        self.assertIn('rust-duty-resident-vertex-probe/v2',diagnostic)
        self.assertIn('capture_skin_stages(',diagnostic)
        self.assertIn('skin_intermediate_errors',diagnostic)
        self.assertIn('identity per-command models',diagnostic)
        self.assertLess(diagnostic.index('"skin_intermediate_errors":intermediate_errors'),
                        diagnostic.index('intermediate_errors.is_empty()'))
        for field in ('uploaded_vertices_hex','draw_uniforms_hex','palette_hex',
                      'cpu_world_position_bits','skin_route_clip_bits','world_route_clip_bits'):
            self.assertIn(field,diagnostic)
        doc=(ROOT/'docs/engineering/resident-skin-stage-diagnostic.md').read_text()
        self.assertIn('compact report/PNG packet alone cannot',doc)
        self.assertIn('can change compiler optimization',doc)


if __name__ == '__main__':
    unittest.main()
