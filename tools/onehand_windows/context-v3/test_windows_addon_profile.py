"""Portable CPU-only Windows-profile checks. No Blender or original addon import.

Run directly on any Python host, including the future Windows source-test job.
Tiny authored CRLF modules are temporary and are removed after each test.
"""
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import linecache
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest import mock
import addon_resolver as a
from candidate_context import ContextError

HERE = Path(__file__).absolute().parent
SOURCE = b'def audited(value):\r\n    return value + 7\r\n'
PACKAGE = b'# Authored synthetic package fixture.\r\n'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(root, source=SOURCE):
    root = Path(root); addon = root / 'scripts/io_scene_fbx'; addon.mkdir(parents=True)
    payloads = {'__init__.py': PACKAGE, 'import_fbx.py': source}
    for name, raw in payloads.items():
        (addon / name).write_bytes(raw)
    pins = copy.deepcopy(a.official_pins())
    pins['files'] = {name: digest(raw) for name, raw in payloads.items()}
    pins['file_metadata'] = {name: a._raw_metadata(raw) for name, raw in payloads.items()}
    pins['raw_functions_sha256'] = {'import_fbx.py': {'audited': digest(source)}}
    pins['loaded_functions_sha256'] = {'import_fbx.py': {'audited': digest(source.replace(b'\r\n', b'\n'))}}
    return addon, pins


def load_fixture_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsAddonProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rd-source-profile-')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(linecache.clearcache)
        self.bundle = Path(self.temp.name).absolute()
        self.root, self.pins = fixture(self.bundle)
        self.files = a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
        self.modules = {'io_scene_fbx': load_fixture_module('_rd_fixture_package', self.root / '__init__.py'),
                        'io_scene_fbx.import_fbx': load_fixture_module('_rd_fixture_importer', self.root / 'import_fbx.py')}

    def verify(self):
        with mock.patch.object(a, 'official_pins', return_value=self.pins):
            return a.verify_loaded_modules(self.files, self.modules)

    def test_real_crlf_module_loaded_source_is_lf_and_raw_unchanged(self):
        fn = self.modules['io_scene_fbx.import_fbx'].audited
        self.assertEqual(fn(5), 12)
        self.assertEqual(inspect.getsource(fn).encode(), SOURCE.replace(b'\r\n', b'\n'))
        self.assertEqual((self.root / 'import_fbx.py').read_bytes(), SOURCE)
        self.assertNotEqual(digest(SOURCE), digest(inspect.getsource(fn).encode()))
        result = self.verify()
        self.assertEqual(result['functions_sha256'], self.pins['loaded_functions_sha256'])
        self.assertEqual(result['raw_functions_sha256'], self.pins['raw_functions_sha256'])
        self.assertFalse(result['windows_execution_proved'])
        self.assertTrue(result['live_function_code_checked'])

    def test_recorded_tiny_module_evidence_is_reproducible(self):
        evidence = json.loads((HERE / 'LOADED_SOURCE_EVIDENCE.json').read_bytes())
        raw = b'def authored_probe(value):\r\n    return value + 7\r\n'
        path = self.bundle / 'authored_probe.py'; path.write_bytes(raw)
        module = load_fixture_module('_rd_recorded_domain_probe', path)
        self.assertEqual(len(raw), evidence['tiny_module_bytes'])
        self.assertEqual(digest(raw), evidence['tiny_module_raw_sha256'])
        self.assertEqual(digest(inspect.getsource(module.authored_probe).encode()), evidence['tiny_loaded_source_sha256'])
        self.assertEqual(module.authored_probe(5), evidence['tiny_module_result'])
        self.assertEqual(path.read_bytes(), raw)

    def test_expected_raw_and_loaded_domains_are_separate(self):
        pins = a.official_pins()
        self.assertNotEqual(pins['raw_functions_sha256'], pins['loaded_functions_sha256'])
        self.assertEqual(pins['loaded_functions_sha256'], {'import_fbx.py': {
            'blen_read_animations': '757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2',
            'blen_store_keyframes_multi': '793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}})
        self.assertEqual(pins['raw_functions_sha256'], {'import_fbx.py': {
            'blen_read_animations': 'd4a7f77069ec1c25036cf6760558dc42ceed0b4e63fc0ffa2524e5fc5f267264',
            'blen_store_keyframes_multi': 'd4ff67c4e021e56d0252bee2b71e32667764620ab6faa8899a11bd2778c6ec44'}})

    def test_every_raw_file_rejects_tamper_and_newline_conversion(self):
        for name in self.files:
            original = self.files[name].read_bytes()
            variants = [original.replace(b'\r\n', b'\n'), original.replace(b'\r\n', b'\n', 1),
                        original + b'\r\n', b'X' + original[1:]]
            for changed in variants:
                with self.subTest(name=name, sha=digest(changed)):
                    self.files[name].write_bytes(changed)
                    try:
                        with self.assertRaisesRegex(ContextError, 'exact bytes'):
                            a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)
                    finally:
                        self.files[name].write_bytes(original)

    def test_changed_raw_file_after_resolution_is_rejected_before_inspect(self):
        self.files['__init__.py'].write_bytes(PACKAGE.replace(b'\r\n', b'\n'))
        with mock.patch.object(inspect, 'getsource', side_effect=AssertionError('must not inspect')):
            with self.assertRaisesRegex(ContextError, 'exact bytes'): self.verify()

    def test_loaded_hash_cannot_replace_raw_function_pin(self):
        self.pins['raw_functions_sha256'] = copy.deepcopy(self.pins['loaded_functions_sha256'])
        with self.assertRaisesRegex(ContextError, 'raw audited function source'):
            a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)

    def test_raw_hash_cannot_replace_loaded_function_pin(self):
        self.pins['loaded_functions_sha256'] = copy.deepcopy(self.pins['raw_functions_sha256'])
        with self.assertRaisesRegex(ContextError, 'live audited function source'): self.verify()

    def test_wrong_profile_schema_distribution_or_version_fails(self):
        for key, value in [('schema', 'rust-duty-logical-official-fbx-pins/v1'),
                           ('profile_id', 'linux-or-any-normalized-profile'),
                           ('blender_version', [4, 3, 3]),
                           ('distribution', {**a.DISTRIBUTION, 'sha256': '0' * 64})]:
            with self.subTest(key=key):
                pins = copy.deepcopy(self.pins); pins[key] = value
                with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)

    def test_wrong_or_collapsed_domain_labels_fail(self):
        for domain in a.HASH_DOMAINS:
            pins = copy.deepcopy(self.pins); pins['hash_domains'][domain] = 'normalized-or-alternative-hash'
            with self.assertRaisesRegex(ContextError, 'hash domains'):
                a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)
        pins = copy.deepcopy(self.pins); pins['functions'] = pins.pop('raw_functions_sha256')
        with self.assertRaisesRegex(ContextError, 'missing or unknown'):
            a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)

    def test_list_of_accepted_hash_alternatives_is_rejected(self):
        self.pins['files']['import_fbx.py'] = [digest(SOURCE), digest(SOURCE.replace(b'\r\n', b'\n'))]
        with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)

    def test_raw_metadata_is_strict_and_not_boolean_counts(self):
        for key, bad in [('bytes', len(SOURCE) + 1), ('crlf_count', 1), ('crlf_count', True),
                         ('bare_cr_count', 1), ('bare_lf_count', 1)]:
            pins = copy.deepcopy(self.pins); pins['file_metadata']['import_fbx.py'][key] = bad
            with self.subTest(key=key, bad=bad):
                with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)

    def test_manifest_raw_pin_is_mandatory(self):
        with mock.patch.object(a, 'PIN_FILE_SHA', '0' * 64):
            with self.assertRaisesRegex(ContextError, 'pin manifest differs'): a.official_pins()

    def test_manifest_inventory_is_exact(self):
        pins = a.official_pins()
        self.assertEqual(len(pins['files']), 10)
        self.assertEqual(set(pins['files']), set(pins['file_metadata']))
        self.assertEqual(set(pins['raw_functions_sha256']['import_fbx.py']),
                         {'blen_read_animations', 'blen_store_keyframes_multi'})
        self.assertEqual(pins['observation']['report_sha256'],
                         '5ee21d576be9af34c7b4095352aca1b4fde329eca23b79b6f12a189edc9d800a')

    def test_unknown_or_missing_fields_fail(self):
        for field in ('raw_functions_sha256', 'loaded_functions_sha256', 'file_metadata', 'profile_id'):
            pins = copy.deepcopy(self.pins); del pins[field]
            with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)
        pins = copy.deepcopy(self.pins); pins['normalize'] = True
        with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)

    def test_function_inventory_and_raw_source_are_exact(self):
        for replacement in ({'missing': digest(SOURCE)}, {'audited': '0' * 64}):
            pins = copy.deepcopy(self.pins); pins['raw_functions_sha256']['import_fbx.py'] = replacement
            if 'missing' in replacement:
                pins['loaded_functions_sha256']['import_fbx.py'] = replacement
            with self.assertRaises(ContextError): a._resolve(self.bundle, 'scripts/io_scene_fbx', pins)

    def test_all_raw_files_checked_before_function_source(self):
        self.files['__init__.py'].write_bytes(b'# Wrong.\r\n')
        with mock.patch.object(ast, 'parse', side_effect=AssertionError('must not derive functions')):
            with self.assertRaisesRegex(ContextError, 'exact bytes'):
                a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)

    def test_shadow_module_file_is_rejected(self):
        shadow = self.bundle / 'shadow.py'; shadow.write_bytes(PACKAGE)
        self.modules['io_scene_fbx'].__file__ = str(shadow)
        with self.assertRaisesRegex(ContextError, 'shadow addon module'): self.verify()

    def test_shadow_spec_origin_is_rejected(self):
        self.modules['io_scene_fbx'].__spec__.origin = str(self.files['import_fbx.py'])
        with self.assertRaisesRegex(ContextError, 'spec origin'): self.verify()

    def test_shadow_function_code_filename_is_rejected(self):
        self.modules['io_scene_fbx.import_fbx'].audited = lambda value: value + 7
        with self.assertRaisesRegex(ContextError, 'shadow or replaced'): self.verify()

    def test_same_origin_code_constant_mutation_is_rejected(self):
        function = self.modules['io_scene_fbx.import_fbx'].audited
        expected_source = inspect.getsource(function)
        function.__code__ = function.__code__.replace(co_consts=(None, 999))
        self.assertEqual(function(5), 1004)
        self.assertEqual(inspect.getsource(function), expected_source)
        self.assertEqual((self.root / 'import_fbx.py').read_bytes(), SOURCE)
        with self.assertRaisesRegex(ContextError, 'live audited function code differs'): self.verify()

    def test_verification_compiles_but_never_executes_raw_module(self):
        # Module-level execution would fail. Define the function from its AST only.
        raw = SOURCE + b"\r\nraise AssertionError('must not execute module')\r\n"
        path = self.files['import_fbx.py']; path.write_bytes(raw)
        self.pins['files']['import_fbx.py'] = digest(raw)
        self.pins['file_metadata']['import_fbx.py'] = a._raw_metadata(raw)
        node = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef))
        module = self.modules['io_scene_fbx.import_fbx']
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec', dont_inherit=True), module.__dict__)
        result = self.verify()
        self.assertTrue(result['live_function_code_checked'])

    def test_missing_required_module_is_rejected(self):
        del self.modules['io_scene_fbx.import_fbx']
        with self.assertRaisesRegex(ContextError, 'must be observed'): self.verify()

    def test_unknown_module_is_rejected(self):
        self.modules['io_scene_fbx.unknown'] = ModuleType('unknown')
        with self.assertRaisesRegex(ContextError, 'unreviewed addon submodule'): self.verify()

    def test_incomplete_raw_inventory_is_rejected(self):
        del self.files['__init__.py']
        with self.assertRaisesRegex(ContextError, 'complete pinned'): self.verify()

    def test_path_escape_is_rejected(self):
        for rel in ('../io_scene_fbx', '/io_scene_fbx', 'scripts\\io_scene_fbx', 'scripts/./io_scene_fbx'):
            with self.subTest(rel=rel):
                with self.assertRaises(ContextError): a._resolve(self.bundle, rel, self.pins)

    def test_symlink_file_is_rejected(self):
        target = self.files['import_fbx.py']; other = self.bundle / 'other.py'; target.rename(other)
        try:
            target.symlink_to(other)
        except OSError as e:
            # Windows hosts without symlink privilege still execute all other checks.
            self.skipTest('host does not permit synthetic symlink creation: ' + type(e).__name__)
        with self.assertRaisesRegex(ContextError, 'symlink'):
            a._resolve(self.bundle, 'scripts/io_scene_fbx', self.pins)

    def test_runtime_resolver_has_no_reconstruction_or_writing_route(self):
        tree = ast.parse((HERE / 'addon_resolver.py').read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module]
                self.assertFalse(set(names) & {'bpy', 'subprocess', 'reconstruct_windows_profile'})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {'replace', 'write_bytes', 'write_text', 'mkdir', 'unlink'})


if __name__ == '__main__': unittest.main(verbosity=2)
