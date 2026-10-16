"""Synthetic, source-free provenance cases. These fixtures are never motion proof."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import prone_camera_pair as pair
import sample_prone_r15_camera as sampler
import vrpack
from test_prone_camera_pair_r15 import fixture, load

GENERATED = hashlib.sha256(b'original synthetic generated source').hexdigest()


def report_fixture(generated=GENERATED):
    report = copy.deepcopy(pair.R15_EQUIVALENCE_CONTRACT)
    report.update(schema='rust-duty-prone-r15-source-equivalence/v1', passed=True,
        generated_source_sha256=generated, rig_action=pair.R15_RIG_ACTION,
        rig_action_fingerprint=pair.R15_FINGERPRINTS[pair.R15_RIG_ACTION],
        camera_action=pair.R15_CAMERA_ACTION,
        camera_action_fingerprint=pair.R15_FINGERPRINTS[pair.R15_CAMERA_ACTION],
        delta_sha256=report.pop('recipe_sha256'), exact_complete_actions_proved=True,
        non_action_preservation_proved=True, evaluated_pair_equivalence_proved=True,
        source_byte_identity_with_approved=False, runtime_equivalence_proved=False, rendered=False,
        evidence_sha256={'approved_witness':report.pop('approved_witness_sha256'),
                         'regenerated_witness':'b'*64,'replay_receipt':'c'*64,
                         'delta':pair.R15_EQUIVALENCE_CONTRACT['recipe_sha256']})
    return report


def descriptor_fixture(generated=GENERATED):
    report=report_fixture(generated)
    return pair.r15_equivalence_descriptor(report, hashlib.sha256(json.dumps(report).encode()).hexdigest(), generated)


def regenerated_fixture():
    document=fixture()
    document.update(schema=pair.R15_REGENERATED_SIDECAR_SCHEMA,
                    candidate_sha256=GENERATED, source_equivalence=descriptor_fixture())
    return document


class RegeneratedAdmissionTests(unittest.TestCase):
    def test_strict_comparator_exports_measured_hashes_without_admitting_synthetic_motion(self):
        import prone_r15_source_delta as delta
        import run_prone_r15_source_proof as runner
        from test_prone_r15_source_delta import evidence_fixture
        approved, regenerated, replay, recipe = evidence_fixture()
        report = runner.compare_witnesses(approved, regenerated, replay, recipe)
        self.assertEqual(report['approved_motion_sha256'], delta.digest(approved['motion']))
        self.assertEqual(report['regenerated_motion_sha256'], delta.digest(regenerated['motion']))
        self.assertEqual(report['static_hashes_sha256'], delta.digest(recipe['static_hashes']))
        self.assertEqual(report['complete_action_fingerprints'], approved['complete_action_fingerprints'])
        self.assertEqual(report['producer_sha256'], recipe['producer_sha256'])
        self.assertEqual(report['numeric_contract'], approved['motion']['numeric_contract'])
        self.assertEqual(report['source_frame_range'], [1, 69])
        self.assertEqual(report['native_fps'], [60, 1])
        self.assertEqual(report['camera_sample_hz'], 3840)
        report['evidence_sha256'] = {
            'approved_witness': pair.R15_EQUIVALENCE_CONTRACT['approved_witness_sha256'],
            'regenerated_witness': 'b' * 64, 'replay_receipt': 'c' * 64,
            'delta': replay['delta_sha256']}
        # Self-consistent synthetic equality is insufficient for the one pinned
        # approved motion contract, even when the comparison itself passed.
        with self.assertRaisesRegex(vrpack.AssetError, 'contract mismatch'):
            pair.r15_equivalence_descriptor(report, 'a' * 64, replay['generated_source_sha256'])

    def test_v3_receipt_keeps_actual_source_and_validated_descriptor(self):
        document=regenerated_fixture()
        loaded=load(document)
        receipt=loaded.receipt(b'synthetic-vra','d'*64,pair.R15_RIG_ACTION)
        self.assertEqual(receipt['schema'],pair.R15_REGENERATED_RECEIPT_SCHEMA)
        self.assertEqual(receipt['candidate_sha256'],GENERATED)
        self.assertNotEqual(receipt['candidate_sha256'],pair.R15_SOURCE_SHA)
        self.assertEqual(receipt['source_equivalence'],document['source_equivalence'])
        self.assertEqual(receipt['source_equivalence']['approved_source_sha256'],pair.R15_SOURCE_SHA)
        self.assertEqual(receipt['camera_sample_hz'],3840)
        document['source_equivalence']['recipe_sha256']='e'*64
        self.assertNotEqual(loaded.source_equivalence,document['source_equivalence'])

    def test_every_invariant_is_required_and_pinned(self):
        proof=descriptor_fixture()
        for key in pair.R15_EQUIVALENCE_CONTRACT:
            changed=copy.deepcopy(proof);changed[key]='unreviewed'
            with self.subTest(changed=key),self.assertRaises(vrpack.AssetError):
                pair.validate_r15_equivalence_descriptor(changed,GENERATED)
            changed=copy.deepcopy(proof);changed.pop(key)
            with self.subTest(missing=key),self.assertRaises(vrpack.AssetError):
                pair.validate_r15_equivalence_descriptor(changed,GENERATED)

    def test_each_dynamic_digest_is_required(self):
        for key in pair.R15_EQUIVALENCE_DYNAMIC_FIELDS:
            changed=descriptor_fixture();changed[key]='A'*64
            with self.subTest(key=key),self.assertRaises(vrpack.AssetError):
                pair.validate_r15_equivalence_descriptor(changed,GENERATED)

    def test_report_rejects_bare_boolean_or_stale_motion_recipe_witness_clock(self):
        for key,value in [('approved_motion_sha256','e'*64),('regenerated_motion_sha256','e'*64),
                          ('delta_sha256','e'*64),('times_sha256','e'*64),('sample_count',1943),
                          ('generated_source_sha256','e'*64),('rig_action','unreviewed'),
                          ('complete_action_fingerprints',{}),('producer_sha256',{}),
                          ('numeric_contract','rounded to 1e-4'),('camera_sample_hz',480),
                          ('source_frame_range',[0,68]),('rendered',True)]:
            report=report_fixture();report[key]=value
            with self.subTest(key=key),self.assertRaises(vrpack.AssetError):
                pair.r15_equivalence_descriptor(report,'a'*64,GENERATED)
        with self.assertRaises(vrpack.AssetError):
            pair.r15_equivalence_descriptor({'passed':True},'a'*64,GENERATED)
        for key in ('approved_witness','delta'):
            report=report_fixture();report['evidence_sha256'][key]='e'*64
            with self.subTest(evidence=key),self.assertRaises(vrpack.AssetError):
                pair.r15_equivalence_descriptor(report,'a'*64,GENERATED)

    def test_source_and_witness_roles_cannot_be_relabelled(self):
        for source in (pair.R15_SOURCE_SHA,pair.R15_EQUIVALENCE_CONTRACT['base_sha256']):
            with self.subTest(source=source),self.assertRaises(vrpack.AssetError):descriptor_fixture(source)
        proof=descriptor_fixture();proof['regenerated_witness_sha256']=proof['approved_witness_sha256']
        with self.assertRaisesRegex(vrpack.AssetError,'reuses'):pair.validate_r15_equivalence_descriptor(proof,GENERATED)

    def test_missing_or_mismatched_sidecar_proof_fails(self):
        for kind in ('missing','source','extra','clock','action'):
            doc=regenerated_fixture()
            if kind=='missing':doc.pop('source_equivalence')
            elif kind=='source':doc['candidate_sha256']='e'*64
            elif kind=='extra':doc['source_equivalence']['passed']=True
            elif kind=='clock':doc['sample_hz']=480
            else:doc['action_fingerprints'][pair.R15_RIG_ACTION]='e'*64
            with self.subTest(kind=kind),self.assertRaises(vrpack.AssetError):load(doc)

    def test_original_v2_admission_cannot_accept_generated_or_a_proof_override(self):
        original=fixture();self.assertEqual(load(original).receipt(b'x','a'*64,pair.R15_RIG_ACTION)['schema'],pair.R15_RECEIPT_SCHEMA)
        generated=regenerated_fixture();generated['schema']=pair.R15_SIDECAR_SCHEMA
        with self.assertRaisesRegex(vrpack.AssetError,'exact approved'):load(generated)
        original['source_equivalence']=descriptor_fixture()
        with self.assertRaisesRegex(vrpack.AssetError,'exact approved'):load(original)

    def test_sampler_requires_actual_bytes_and_pinned_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic-source';source.write_bytes(b'original synthetic generated source')
            proof=Path(directory)/'proof.json';proof.write_text(json.dumps(report_fixture()))
            proof_sha=hashlib.sha256(proof.read_bytes()).hexdigest()
            actual,descriptor=sampler.source_binding(source,proof,proof_sha)
            self.assertEqual(actual,GENERATED);self.assertEqual(descriptor['source_equivalence_sha256'],proof_sha)
            for args in ((source,), (source,proof), (source,None,proof_sha), (source,proof,'e'*64)):
                with self.subTest(args=str(args)),self.assertRaises(vrpack.AssetError):sampler.source_binding(*args)
            source.write_bytes(b'changed source')
            with self.assertRaisesRegex(vrpack.AssetError,'generated source mismatch'):
                sampler.source_binding(source,proof,proof_sha)
            proof.write_bytes(b'{"schema":1,"schema":2}')
            with self.assertRaisesRegex(vrpack.AssetError,'invalid r15'):
                pair.load_r15_equivalence_report(proof,hashlib.sha256(proof.read_bytes()).hexdigest(),GENERATED)
            proof.write_bytes(b' ' * 65537)
            with self.assertRaisesRegex(vrpack.AssetError,'file bound'):
                pair.load_r15_equivalence_report(proof,hashlib.sha256(proof.read_bytes()).hexdigest(),GENERATED)


if __name__=='__main__':unittest.main()
