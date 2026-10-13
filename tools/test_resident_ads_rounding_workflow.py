"""Keep the diagnostic route bounded, source-bound and separate from acceptance."""
from pathlib import Path
import unittest
import tempfile
import subprocess
from unittest.mock import patch
import run_resident_ads_rounding as diagnostic
from historical_source_test_fixture import resident_ads_sources
import yaml

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT/'.github/workflows/resident-ads-rounding.yml').read_text())
        self.job = self.workflow['jobs']['resident-ads']
        self.steps = self.job['steps']

    def test_owned_branch_read_only_non_canceling_and_no_original_gate_edits(self):
        event = self.workflow.get('on',self.workflow.get(True))
        self.assertEqual(event['push']['branches'],['aella/wgpu-1080p-diagnostics'])
        self.assertEqual(self.workflow['permissions'],{'contents':'read'})
        self.assertFalse(self.workflow['concurrency']['cancel-in-progress'])
        self.assertIn("github.repository == 'RHS059/rust_duty'",self.job['if'])
        self.assertIn("github.ref == 'refs/heads/aella/wgpu-1080p-diagnostics'",self.job['if'])

    def test_exact_public_asset_producers_and_trigger_inputs(self):
        producers={'animation-assets':'blender-assets','walk-assets':'walk-assets','ads-assets':'ads-assets',
                   'directional-assets':'directional-assets','jump-assets':'jump-assets'}
        self.assertEqual(set(self.job['needs']),set(producers)|{'admission'})
        paths=self.workflow.get('on',self.workflow.get(True))['push']['paths']
        for job,file in producers.items():
            self.assertEqual(self.workflow['jobs'][job]['uses'],f'./.github/workflows/{file}.yml')
            self.assertIn(f'.github/workflows/{file}.yml',paths)
        checkout=next(s for s in self.steps if s.get('uses')=='actions/checkout@v4')
        self.assertIn('!/assets/weapons/',checkout['with']['sparse-checkout'])
        self.assertFalse(checkout['with']['persist-credentials'])

    def test_source_admission_accepts_immutable_history_and_skips_changed_production(self):
        production=resident_ads_sources()
        self.assertEqual(diagnostic.matrix.canonical_hash(diagnostic.pair.hashes(production)),
                         diagnostic.PRODUCTION_MANIFEST)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            subprocess.run(['git','-C',str(root),'config','core.autocrlf','false'],check=True,capture_output=True)
            for name,data in production.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            subprocess.run(['git','-C',str(root),'add','.'],check=True,capture_output=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Synthetic Test',
                            '-c','user.email=test@example.invalid','commit','-qm','Historical source fixture'],
                           check=True,capture_output=True)
            self.assertTrue(diagnostic.admit(root))
        changed={**production,'src/main.rs':production['src/main.rs']+b'\n// unreviewed change\n'}
        with patch.object(diagnostic.pair,'read_sources',return_value=changed):
            self.assertFalse(diagnostic.admit(ROOT))
        with patch.object(diagnostic.pair,'read_sources',side_effect=OSError('Git read failed')):
            with self.assertRaises(OSError):
                diagnostic.admit(ROOT)

    def test_current_source_is_not_admitted_to_historical_ads_diagnostic(self):
        self.assertFalse(diagnostic.admit(ROOT))

    def test_every_expensive_job_requires_explicit_source_admission(self):
        for name,job in self.workflow['jobs'].items():
            if name=='admission':
                continue
            self.assertIn('admission',job['needs'])
            self.assertIn("needs.admission.outputs.admitted == 'true'",job['if'])
        admission=self.workflow['jobs']['admission']
        self.assertEqual(admission['outputs']['admitted'],'${{ steps.source.outputs.admitted }}')
        checkout=next(s for s in admission['steps'] if s.get('uses')=='actions/checkout@v4')
        self.assertIn('/*',checkout['with']['sparse-checkout'])
        self.assertIn('!/assets/',checkout['with']['sparse-checkout'])
        command=next(s for s in admission['steps'] if s.get('id')=='source')
        self.assertIn('--admit >> "$GITHUB_OUTPUT"',command['run'])
        self.assertEqual(command['shell'],'bash')

    def test_dependencies_compiler_and_bytecode_precede_every_import(self):
        self.assertEqual(self.workflow['env']['PYTHONDONTWRITEBYTECODE'],'1')
        dependency=next(i for i,s in enumerate(self.steps) if 'pip install Pillow==11.3.0 PyYAML==6.0.3' in s.get('run',''))
        for i,s in enumerate(self.steps):
            if 'python ' in s.get('run','') and 'pip install' not in s['run']:
                self.assertGreater(i,dependency)
        compiler=next(s for s in self.steps if 'rustup which' in s.get('run',''))
        self.assertIn('--toolchain 1.99.0-x86_64-pc-windows-msvc rustc',compiler['run'])
        self.assertIn('GITHUB_PATH',compiler['run'])
        self.assertNotIn('runner.temp',self.job['env']['CARGO_HOME'])

    def test_all_evidence_retained_and_timeout_covers_bounded_four_processes(self):
        capture=next(s for s in self.steps if 'run_resident_ads_rounding.py' in s.get('run',''))
        self.assertGreaterEqual(capture['timeout-minutes']*60,2*1200+2*3000)
        self.assertGreater(self.job['timeout-minutes'],capture['timeout-minutes'])
        uploads=[s for s in self.steps if s.get('uses')=='actions/upload-artifact@v4']
        self.assertEqual(len(uploads),2)
        for s in uploads:
            self.assertTrue(s['id'])
            self.assertEqual(s['if'],'always()')
        self.assertIn('evidence/resident-ads/**',uploads[0]['with']['path'])
        self.assertIn('!evidence/resident-ads/*-target/**',uploads[0]['with']['path'])
        self.assertIn('evidence/resident-ads/*.json',uploads[1]['with']['path'])


if __name__=='__main__':
    unittest.main()
