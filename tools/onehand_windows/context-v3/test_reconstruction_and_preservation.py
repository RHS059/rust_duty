"""Local recovery-source evidence tests; never native or motion-proof execution."""
import ast
import copy
import hashlib
import importlib.machinery
import inspect
import json
import linecache
from pathlib import Path
import tempfile
from types import CodeType, FunctionType, ModuleType
import unittest
from unittest import mock
import addon_resolver as a
import reconstruct_windows_profile as r
from candidate_context import ContextError

HERE = Path(__file__).absolute().parent
PUBLISHED = HERE.parent / 'published-pr77/tools/onehand_windows'
PREDECESSOR = PUBLISHED / 'context-v2'
OBSERVATION = HERE.parent / 'actual-windows-observation-v3/artifact-json/proof/public-evidence/official-addon-observation.json'
LF_ROOT = Path('/usr/share/blender/scripts/addons_core/io_scene_fbx')


def reconstruct():
    return r.reconstruct(LF_ROOT, OBSERVATION, PREDECESSOR)


def reconstructed_bundle(root):
    raw, receipt = reconstruct()
    root = Path(root); addon = root / 'scripts/io_scene_fbx'; addon.mkdir(parents=True)
    for name, value in raw.items(): (addon / name).write_bytes(value)
    return root, receipt


def isolated_audited_functions(path, names):
    """Define only two audited functions without invoking their bodies or addon imports."""
    tree = ast.parse(path.read_bytes())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    assert all(not n.decorator_list and not n.returns and
               all(arg.annotation is None for arg in (*n.args.posonlyargs, *n.args.args, *n.args.kwonlyargs)) and
               all(isinstance(d, ast.Constant) for d in n.args.defaults) and not n.args.kw_defaults for n in nodes)
    module = ModuleType('io_scene_fbx.import_fbx'); module.__file__ = str(path)
    module.__spec__ = importlib.machinery.ModuleSpec(module.__name__, None, origin=str(path))
    compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True, optimize=0)
    codes = {code.co_name: code for code in compiled.co_consts if isinstance(code, CodeType) and code.co_name in names}
    assert set(codes) == set(names)
    for name, code in codes.items():
        setattr(module, name, FunctionType(code, module.__dict__, name))
    return module


class ReconstructionAndPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rd-reconstruction-')
        self.addCleanup(self.temp.cleanup); self.addCleanup(linecache.clearcache)
        self.root = Path(self.temp.name).absolute()

    def test_all_ten_reconstructed_raw_files_and_receipt_are_exact(self):
        raw, receipt = reconstruct(); pins = a.official_pins()
        self.assertEqual(len(raw), 10)
        self.assertEqual(receipt, json.loads((HERE / 'RECONSTRUCTION_EVIDENCE.json').read_bytes()))
        for name, value in raw.items():
            self.assertEqual(r.digest(value), pins['files'][name])
            self.assertEqual(r.raw_metadata(value), pins['file_metadata'][name])
        self.assertEqual(sum(map(len, raw.values())), 551471)

    def test_entire_linux_profile_rejected_by_windows_resolver(self):
        with self.assertRaisesRegex(ContextError, 'exact bytes'):
            a.resolve_addon(Path('/usr/share/blender'), 'scripts/addons_core/io_scene_fbx')

    def test_exact_windows_reconstruction_accepts_without_modifying_source(self):
        bundle, _ = reconstructed_bundle(self.root / 'official')
        before = {p.name: p.read_bytes() for p in LF_ROOT.glob('*.py')}
        files = a.resolve_addon(bundle, 'scripts/io_scene_fbx')
        self.assertEqual(len(files), 10)
        for name, raw in before.items(): self.assertEqual((LF_ROOT / name).read_bytes(), raw)

    def test_each_of_ten_whole_raw_files_rejects_a_one_byte_mutation(self):
        bundle, _ = reconstructed_bundle(self.root / 'official'); files = a.resolve_addon(bundle, 'scripts/io_scene_fbx')
        for name, path in files.items():
            original = path.read_bytes(); path.write_bytes(b'X' + original[1:])
            try:
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ContextError, 'exact bytes'):
                        a.resolve_addon(bundle, 'scripts/io_scene_fbx')
            finally: path.write_bytes(original)

    def test_raw_function_hashes_match_exact_recorded_line_ranges(self):
        raw, receipt = reconstruct(); pins = a.official_pins()
        for name, funcs in receipt['raw_function_slices'].items():
            for func, record in funcs.items():
                source = b''.join(raw[name].splitlines(keepends=True)[record['start_line'] - 1:record['end_line']])
                self.assertEqual(r.digest(source), pins['raw_functions_sha256'][name][func])
                self.assertEqual(r.raw_metadata(source), {k: record[k] for k in r.raw_metadata(source)})

    def test_actual_audited_inspect_hashes_keep_original_loaded_pins(self):
        bundle, _ = reconstructed_bundle(self.root / 'official'); files = a.resolve_addon(bundle, 'scripts/io_scene_fbx')
        pins = a.official_pins(); path = files['import_fbx.py']; before = path.read_bytes()
        importer = isolated_audited_functions(path, pins['loaded_functions_sha256']['import_fbx.py'])
        package = ModuleType('io_scene_fbx'); package.__file__ = str(files['__init__.py'])
        package.__spec__ = importlib.machinery.ModuleSpec(package.__name__, None, origin=package.__file__)
        result = a.verify_loaded_modules(files, {'io_scene_fbx': package, 'io_scene_fbx.import_fbx': importer})
        old = json.loads((PREDECESSOR / 'OFFICIAL_ADDON_PINS.json').read_bytes())
        self.assertEqual(result['functions_sha256'], old['functions'])
        for name, expected in old['functions']['import_fbx.py'].items():
            source = inspect.getsource(getattr(importer, name)).encode()
            self.assertEqual(r.digest(source), expected); self.assertNotIn(b'\r', source)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(result['windows_execution_proved'])

    def test_bad_lf_source_rejected_before_any_function_derivation(self):
        copied = self.root / 'lf'; copied.mkdir()
        for path in LF_ROOT.glob('*.py'): (copied / path.name).write_bytes(path.read_bytes())
        (copied / 'parse_fbx.py').write_bytes(b'# bad\n')
        with mock.patch.object(r, 'function_slices', side_effect=AssertionError('must not derive')):
            with self.assertRaisesRegex(ContextError, 'historical exact LF'):
                r.reconstruct(copied, OBSERVATION, PREDECESSOR)

    def test_bad_observation_bytes_rejected_before_any_derivation(self):
        path = self.root / 'observation.json'; path.write_bytes(OBSERVATION.read_bytes() + b'\n')
        with mock.patch.object(r, 'function_slices', side_effect=AssertionError('must not derive')):
            with self.assertRaisesRegex(ContextError, 'report exact bytes'):
                r.reconstruct(LF_ROOT, path, PREDECESSOR)

    def test_reconstruction_has_no_write_or_native_routes(self):
        tree = ast.parse((HERE / 'reconstruct_windows_profile.py').read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {'write_bytes', 'write_text', 'unlink', 'mkdir', 'Popen', 'run'})

    def test_original_context_metadata_math_wrappers_and_helper_pins_are_byte_identical(self):
        for name in ('candidate_context.py', 'production_assembler.py', 'pinned_assembler.py',
                     'pinned_transport.py', 'NATIVE_HELPER_PINS.json', 'verify_freeze.py'):
            self.assertEqual((HERE / name).read_bytes(), (PREDECESSOR / name).read_bytes(), name)

    def test_both_predecessor_package_freezes_remain_exact(self):
        for name, expected in [('context-v1', 'cee1e6fc907638c6eaa363fd301b722b145767ae1d19131519a53b9b74c9d378'),
                               ('context-v2', r.PREDECESSOR_SHA)]:
            root = PUBLISHED / name; self.assertEqual(r.digest((root / 'PINS.json').read_bytes()), expected)
            for file, wanted in json.loads((root / 'PINS.json').read_bytes()).items():
                self.assertEqual(r.digest((root / file).read_bytes()), wanted)

    def test_hash_only_evidence_contains_no_addon_source_or_private_url(self):
        for filename in ('OFFICIAL_ADDON_PINS.json', 'RECONSTRUCTION_EVIDENCE.json', 'LOADED_SOURCE_EVIDENCE.json'):
            raw = (HERE / filename).read_bytes()
            self.assertNotIn(b'https://', raw); self.assertNotIn(b'def blen_', raw)
            json.loads(raw)


if __name__ == '__main__': unittest.main(verbosity=2)
