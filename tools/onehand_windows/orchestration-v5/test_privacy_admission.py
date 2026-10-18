import json,unittest
import workflow_core as w
import orchestrate,preinstall_admission as a,projection_binding as p
class PrivacyAdmission(unittest.TestCase):
 def test_null_admission_stays_blocked(self):self.assertEqual(a.admission_state(w.strict_json(w.HERE/'admission.template.json')),'blocked-incomplete-admission')
 def test_summary_does_not_promise_retention_or_capture(self):
  s=orchestrate.summary({});self.assertEqual(s['candidate_retention'],'private runner-local until teardown');self.assertIsNone(s['runtime_asset_artifact_route']);self.assertFalse(s['game_capture_performed']);self.assertFalse(s['game_capture_binding_reviewed']);self.assertEqual(s['source_projection_sha256'],p.PROJECTION_SHA)
 def test_transport_targets_projected_delta(self):
  rows=w.strict_json(w.HERE/'RAW_INPUT_PINS.json')['files'];self.assertEqual(len(rows),38);self.assertEqual(rows[0]['sha256'],p.PROJECTED_DELTA_SHA);self.assertNotEqual(rows[0]['sha256'],'7be513e2c9fa5d0ff1c00684c542a73354d49fd561fd406a08dad8e05c219a9d')
 def test_active_workflow_still_uploads_only_hash_summaries(self):
  s=(w.HERE/'onehand-windows-proof.yml').read_text();self.assertNotIn('/runtime/',s);self.assertNotIn('capture-candidate.json',s)
if __name__=='__main__':unittest.main()
