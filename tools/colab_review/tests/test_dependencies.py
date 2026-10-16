import importlib.metadata, json, sys, types, unittest
from pathlib import Path
from unittest.mock import patch

class TestDependencies(unittest.TestCase):
 def setup_source(self):
  nb=json.loads((Path(__file__).parents[1]/'Rust_Duty_Animation_Review.ipynb').read_text())
  c=next(c for c in nb['cells'] if c['id']=='review-01')
  return '\n'.join(line for line in ''.join(c['source']).splitlines() if not line.startswith('%pip'))
 def run_guard(self,installed='2.2.6',loaded='2.2.6',requirements=('numpy<2.3,>=1.24',)):
  with patch.object(importlib.metadata,'version',return_value=installed),patch.object(importlib.metadata,'requires',return_value=requirements),patch.dict(sys.modules,{'numpy':types.SimpleNamespace(__version__=loaded)}):
   exec(self.setup_source(),{})
 def test_compatible(self):self.run_guard()
 def test_pin_mismatch(self):
  with self.assertRaisesRegex(RuntimeError,'installation'):self.run_guard(installed='2.3.5')
 def test_stale_loaded_module(self):
  with self.assertRaisesRegex(RuntimeError,'already imported'):self.run_guard(loaded='2.3.5')
 def test_numba_conflict(self):
  with self.assertRaisesRegex(RuntimeError,'Numba requires'):self.run_guard(requirements=('numpy<2.2',))
 def test_inactive_marker(self):self.run_guard(requirements=('numpy<2.2; python_version < "3.0"',))
