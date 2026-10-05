"""Every complete quality lane installs the workflow-parser dependency explicitly."""
from pathlib import Path
import unittest
import yaml


class QualityDependencyTests(unittest.TestCase):
    def test_all_full_quality_jobs_install_pinned_yaml_before_discovery(self):
        root=Path(__file__).resolve().parents[1]/'.github/workflows'
        checked=[]
        for filename in ('build.yml','native-validation.yml','windows-source-bound-recovery.yml'):
            jobs=yaml.safe_load((root/filename).read_text())['jobs']
            found=False
            for name,job in jobs.items():
                steps=job.get('steps',[])
                for index,step in enumerate(steps):
                    if 'ci_quality_checks.py' not in step.get('run',''):
                        continue
                    found=True
                    preceding=[row.get('run','') for row in steps[:index]]
                    self.assertTrue(any('python -m pip install' in run and 'PyYAML==6.0.3' in run for run in preceding),
                                    f'{filename}/{name}: workflow parser dependency is undeclared')
                    checked.append((filename,name))
            self.assertTrue(found,filename)
        self.assertEqual(len(checked),3)


if __name__=='__main__':
    unittest.main()
