"""Synthetic strict identity tests; no baseline, delta payload or native execution."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import candidate_context as c
from test_candidate_context import synthetic_context, synthetic_authored, tmp

HERE = Path(__file__).absolute().parent

class MetadataProjectionTests(unittest.TestCase):
    def setUp(self):
        self.raw = synthetic_context(tmp())
        self.ctx = c.ProofContext.parse(self.raw)
        self.receipt = synthetic_authored(self.ctx)

    def test_exact_explicit_bridge_v2_binds_projected_metadata(self):
        self.assertEqual(self.ctx.validate_authored_receipt(self.receipt), self.receipt)
        self.assertEqual(self.receipt['metadata_projection']['projected_metadata_sha256'],
                         dict(self.ctx.action_hashes)['metadata'])
        self.assertFalse(self.receipt['metadata_projection']['historical_reference_resampled'])
        self.assertEqual(self.ctx.pin('original_delta').sha256, c.DELTA_SHA)
        self.assertNotEqual(c.DELTA_SHA, c.ORIGINAL_DELTA_SHA)
        self.assertEqual(len(c.OMITTED_METADATA_KEYS), 9)
        self.assertEqual(len(set(c.OMITTED_METADATA_KEYS)), 9)

    def test_original_receipt_schema_cannot_claim_projection(self):
        self.receipt['schema'] = 'rust-duty-onehand-authored-input-bridge/v1'
        with self.assertRaisesRegex(c.ContextError, 'schema'):
            self.ctx.validate_authored_receipt(self.receipt)

    def test_original_delta_cannot_be_substituted_for_projected_bytes(self):
        self.raw['files']['original_delta']['sha256'] = c.ORIGINAL_DELTA_SHA
        with self.assertRaisesRegex(c.ContextError, 'immutable identity'):
            c.ProofContext.parse(self.raw)

    def test_projection_is_required_and_has_exact_fields(self):
        for mutation in ('absent', 'unknown', 'missing'):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(self.receipt)
                if mutation == 'absent': del value['metadata_projection']
                elif mutation == 'unknown': value['metadata_projection']['approved'] = True
                else: del value['metadata_projection']['metadata_recipe_sha256']
                with self.assertRaisesRegex(c.ContextError, 'missing or unknown'):
                    self.ctx.validate_authored_receipt(value)

    def test_each_projection_identity_and_claim_is_exact(self):
        bad = {'schema': 'old', 'projection_sha256': 'f' * 64,
               'original_delta_sha256': c.DELTA_SHA, 'original_metadata_sha256': 'e' * 64,
               'metadata_recipe_sha256': 'd' * 64, 'projected_metadata_sha256': 'c' * 64,
               'omitted_keys': list(c.OMITTED_METADATA_KEYS[:-1]),
               'historical_reference_resampled': True}
        for field, wrong in bad.items():
            with self.subTest(field=field):
                value = copy.deepcopy(self.receipt); value['metadata_projection'][field] = wrong
                with self.assertRaisesRegex(c.ContextError, 'metadata projection'):
                    self.ctx.validate_authored_receipt(value)

    def test_no_guessed_or_null_projected_metadata(self):
        for wrong in (None, '', 0, False, c.ORIGINAL_METADATA_SHA):
            with self.subTest(wrong=wrong):
                value = copy.deepcopy(self.receipt)
                value['metadata_projection']['projected_metadata_sha256'] = wrong
                with self.assertRaises(c.ContextError): self.ctx.validate_authored_receipt(value)

    def test_false_resampling_flag_is_not_integer_zero(self):
        self.receipt['metadata_projection']['historical_reference_resampled'] = 0
        with self.assertRaises(c.ContextError): self.ctx.validate_authored_receipt(self.receipt)

    def test_omitted_keys_order_and_no_extra_deletion(self):
        for wrong in (list(reversed(c.OMITTED_METADATA_KEYS)), [*c.OMITTED_METADATA_KEYS, 'new_key']):
            value = copy.deepcopy(self.receipt); value['metadata_projection']['omitted_keys'] = wrong
            with self.assertRaises(c.ContextError): self.ctx.validate_authored_receipt(value)

    def test_source_projection_binding_matches_exact_context_interface(self):
        from types import ModuleType
        root=HERE.parent/'source-producer-privacy-v1'
        self.assertEqual(c.file_sha(root/'PINS.json'),c.SOURCE_PINS_SHA)
        for name,want in c.strict_json(root/'PINS.json').items():
            self.assertEqual(c.file_sha(root/name),want,name)
        module=ModuleType('_verified_projection_interface');module.__file__=str(root/'privacy_projection.py')
        exec(compile((root/'privacy_projection.py').read_bytes(),module.__file__,'exec'),module.__dict__)
        value=dict(self.ctx.action_hashes)['metadata']
        self.assertEqual(module.binding(value),c.metadata_projection_binding(value))
        bridge=HERE.parent/'windows-privacy-bridge-v1/authored_bridge.py'
        self.assertEqual(c.file_sha(bridge),c.BRIDGE_SHA)

    def test_numerical_invariants_and_wrappers_remain_unchanged(self):
        previous = HERE.parent / 'windows-candidate-context-v1'
        for name in ('production_assembler.py', 'pinned_assembler.py', 'pinned_transport.py',
                     'addon_resolver.py', 'NATIVE_HELPER_PINS.json', 'OFFICIAL_ADDON_PINS.json'):
            self.assertEqual((HERE / name).read_bytes(), (previous / name).read_bytes(), name)
        import ast
        old_tree = ast.parse((previous / 'candidate_context.py').read_bytes())
        new_tree = ast.parse((HERE / 'candidate_context.py').read_bytes())
        def invariants(tree):
            return ast.dump(next(n for n in tree.body if isinstance(n, ast.Assign)
                                 and any(isinstance(t, ast.Name) and t.id == 'INVARIANTS' for t in n.targets)))
        self.assertEqual(invariants(old_tree), invariants(new_tree))

if __name__ == '__main__': unittest.main(verbosity=2)
