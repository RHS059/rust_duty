"""Stdlib-only fragment compatibility and fail-closed integrity regressions.

Run unchanged with actual CPython 3.11 and 3.12. The explicitly named schema
projection test is not evidence of an actual 3.11 parser on a 3.12 host.
"""
import ast
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from test_rigid_json_cap import original_native_stages_sha
import pinned_code as compat
import pinned_code

HERE = Path(__file__).absolute().parent
FROZEN_SHA = '3a2d0c7ea5fcc0dfab7ec615dbb78e0b7d9f907c1d1a48bc2f90da14933952b5'

def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()

def data():
    return json.loads((HERE / 'AUDITED_FRAGMENTS.json').read_text())

def original_pinned_code_sha():
    source = (HERE / 'pinned_code.py').read_text()
    begin = '# BEGIN FROZEN FRAGMENT AST COMPATIBILITY\n'
    end = '# END FROZEN FRAGMENT AST COMPATIBILITY\n\n'
    assert source.count(begin) == source.count(end) == 1
    prefix, tail = source.split(begin)
    block, suffix = tail.split(end)
    assert 'def audited_ast_dump(tree):' in block
    source = prefix + suffix
    new = "audited_ast_dump(ast.parse(rec['source']))"
    old = "ast.dump(ast.parse(rec['source']),include_attributes=False)"
    assert source.count(new) == 1
    return sha(source.replace(new, old))

class FragmentCompatibility(unittest.TestCase):
    def test_declared_serializer_only_source_change(self):
        self.assertEqual(original_pinned_code_sha(), '193c247bea1c7c48fd4a9e16b5d2b88111472353fedeb6622f5a3e1392fe61fd')

    def test_all_other_production_files_unchanged(self):
        predecessor = json.loads((HERE / 'AST_COMPAT_PREDECESSOR.json').read_text())
        self.assertEqual(predecessor['pins_sha256'], 'fbf3b0f7221b34b6dca29b885c7b1ab2f965ed76049c77504b9d504032e5bc9e')
        for name, wanted in predecessor['files'].items():
            if name.endswith('.py') and not name.startswith('test_') and name != 'pinned_code.py':
                self.assertEqual(original_native_stages_sha() if name == 'native_stages.py' else pinned_code.file_sha(HERE / name), wanted, name)

    def test_frozen_fragment_file_unchanged(self):
        self.assertEqual(pinned_code.file_sha(HERE / 'AUDITED_FRAGMENTS.json'), FROZEN_SHA)

    def test_all_34_original_ast_hashes(self):
        records = pinned_code.fragments()['fragments']
        self.assertEqual(len(records), 34)
        for name, rec in records.items():
            with self.subTest(fragment=name):
                self.assertEqual(sha(rec['source']), rec['source_sha256'])
                self.assertEqual(sha(compat.audited_ast_dump(ast.parse(rec['source']))), rec['original_ast_sha256'])

    def test_native_dump_version_delta_exact(self):
        mismatches = []
        for name, rec in data()['fragments'].items():
            if sha(ast.dump(ast.parse(rec['source']), include_attributes=False)) != rec['original_ast_sha256']:
                mismatches.append(name)
        self.assertEqual(len(mismatches), 28 if sys.version_info[:2] == (3, 11) else 0)
        if mismatches:
            self.assertEqual(mismatches[0], 'GeometryBytes')

    def test_exact_73_kind_inventory(self):
        kinds = {type(node).__name__ for rec in data()['fragments'].values() for node in ast.walk(ast.parse(rec['source']))}
        self.assertEqual(len(kinds), 73)
        self.assertEqual(kinds, set(compat._FIELDS_312))

    def test_exact_definition_inventory(self):
        counts = {'FunctionDef': 0, 'ClassDef': 0}
        for rec in data()['fragments'].values():
            for node in ast.walk(ast.parse(rec['source'])):
                if type(node).__name__ in counts:
                    counts[type(node).__name__] += 1
        self.assertEqual(counts, {'FunctionDef': 35, 'ClassDef': 2})

    def test_all_original_and_relocated_trees_compile(self):
        for name, rec in data()['fragments'].items():
            with self.subTest(fragment=name):
                compile(ast.parse(rec['source']), 'original:' + name, 'exec', dont_inherit=True)
                compile(pinned_code.fragment_tree(name), 'relocated:' + name, 'exec', dont_inherit=True)

    def test_exact_three_existing_relocations(self):
        changed = []
        paths = recipes = 0
        for name, rec in data()['fragments'].items():
            original = ast.parse(rec['source'])
            transform = pinned_code.Relocate(rec)
            result = transform.visit(copy.deepcopy(original))
            paths += transform.paths
            recipes += transform.recipes
            if ast.dump(original) != ast.dump(result):
                changed.append(name)
        self.assertEqual(set(changed), {'import_window', 'import_exact_grid'})
        self.assertEqual((paths, recipes), (2, 1))

    def test_serializer_does_not_mutate_execution_tree(self):
        for rec in data()['fragments'].values():
            tree = ast.parse(rec['source'])
            before = ast.dump(tree, include_attributes=True)
            attributes = [dict(vars(node)) for node in ast.walk(tree)]
            compat.audited_ast_dump(tree)
            self.assertEqual(ast.dump(tree, include_attributes=True), before)
            self.assertEqual([dict(vars(node)) for node in ast.walk(tree)], attributes)

    def test_311_schema_projection_on_312_is_explicitly_simulated(self):
        if sys.version_info[:2] != (3, 12):
            # Actual 3.11 has stronger direct parser coverage in the other tests.
            self.assertEqual(sys.version_info[:2], (3, 11))
            return
        records = data()['fragments']
        trees = {name: ast.parse(rec['source']) for name, rec in records.items()}
        for tree in trees.values():
            for node in ast.walk(tree):
                if type(node).__name__ in compat._DEFINITIONS:
                    del node.type_params
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'version_info', (3, 11, 9)))
            for name in compat._DEFINITIONS:
                stack.enter_context(patch.object(getattr(ast, name), '_fields', compat._FIELDS_312[name][:-1]))
            for name, tree in trees.items():
                before = ast.dump(tree, include_attributes=True)
                self.assertEqual(sha(compat.audited_ast_dump(tree)), records[name]['original_ast_sha256'])
                self.assertEqual(ast.dump(tree, include_attributes=True), before)

    def test_unsupported_versions_fail_closed(self):
        tree = ast.parse('x = 1')
        for version in ((3, 10), (3, 13), (3, 14), (4, 0)):
            with self.subTest(version=version), patch.object(sys, 'version_info', version):
                with self.assertRaisesRegex(ValueError, 'requires CPython'):
                    compat.audited_ast_dump(tree)

    def test_non_cpython_fails_closed(self):
        with patch.object(sys, 'implementation', types.SimpleNamespace(name='pypy')):
            with self.assertRaisesRegex(ValueError, 'requires CPython'):
                compat.audited_ast_dump(ast.parse('x = 1'))

    def test_unknown_syntax_kind_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside frozen grammar'):
            compat.audited_ast_dump(ast.parse('x = (y := 1)'))

    def test_unknown_field_layout_rejected(self):
        tree = ast.parse('x = 1')
        tree.body[0]._fields += ('unexpected_semantics',)
        tree.body[0].unexpected_semantics = True
        with self.assertRaisesRegex(ValueError, 'field layout differs'):
            compat.audited_ast_dump(tree)

    def test_missing_field_rejected(self):
        tree = ast.parse('def f():\n    return 1\n')
        del tree.body[0].returns
        with self.assertRaisesRegex(ValueError, 'field missing'):
            compat.audited_ast_dump(tree)

    def test_extra_field_not_silently_dropped(self):
        tree = ast.parse('x = 1')
        tree.body[0].unexpected_semantics = True
        with self.assertRaisesRegex(ValueError, 'extra field'):
            compat.audited_ast_dump(tree)

    def test_nonempty_or_invalid_type_params_rejected(self):
        for value in ([ast.Name(id='T', ctx=ast.Load())], (), None):
            tree = ast.parse('def f():\n    return 1\n')
            tree.body[0].type_params = value
            with self.assertRaisesRegex(ValueError, 'type parameters must be empty|extra field'):
                compat.audited_ast_dump(tree)

    def check_record_rejected(self, changed, message):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'AUDITED_FRAGMENTS.json').write_text(json.dumps(changed))
            with patch.object(pinned_code, 'HERE', root):
                with self.assertRaisesRegex(ValueError, message):
                    pinned_code.fragments()

    def test_changed_source_bytes_rejected(self):
        changed = data()
        changed['fragments']['GeometryBytes']['source'] += '\n'
        self.check_record_rejected(changed, 'fragment source hash differs')

    def test_rehashed_semantic_mutations_rejected_by_original_ast(self):
        mutations = [("dtype='<i8'", "dtype='<i4'"), ('start + size', 'start - size'),
                     ('frozen=True', 'frozen=False'), ('vertex_count: int', 'vertex_count: str'),
                     ('def polygons(self):', 'def polygons(self, extra=None):')]
        for old, new in mutations:
            changed = data()
            rec = changed['fragments']['GeometryBytes']
            self.assertIn(old, rec['source'])
            rec['source'] = rec['source'].replace(old, new, 1)
            rec['source_sha256'] = sha(rec['source'])
            with self.subTest(mutation=old):
                self.check_record_rejected(changed, 'fragment AST differs')

    def test_original_ast_hash_mutation_rejected(self):
        changed = data()
        changed['fragments']['GeometryBytes']['original_ast_sha256'] = '0' * 64
        self.check_record_rejected(changed, 'fragment AST differs')

    def test_signed_zero_literal_distinction_preserved(self):
        self.assertNotEqual(compat.audited_ast_dump(ast.parse('x = 0.0')),
                            compat.audited_ast_dump(ast.parse('x = -0.0')))

    def test_no_native_application_imported(self):
        self.assertNotIn('bpy', sys.modules)

if __name__ == '__main__':
    unittest.main(verbosity=2)
