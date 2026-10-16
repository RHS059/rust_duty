"""Source-free r15 admission probes; synthetic matrices are never production evidence."""
from fractions import Fraction
import hashlib,json,unittest
import prone_camera_pair as pair
import vrpack
from test_prone_camera_pair import rows,translation

def fixture():
    samples=[]
    for i in range(4353):
        m=translation(0,0,-1.26*i/4352)
        samples.append({'candidate_frame':1+i/64,'time_seconds':i/3840,
                        'camera_world':rows(m),'common_world_delta':rows(m)})
    return {'schema':pair.R15_SIDECAR_SCHEMA,'candidate_sha256':pair.R15_SOURCE_SHA,
            'action_fingerprints':dict(pair.R15_FINGERPRINTS),'units':'metres and radians; Blender world +Z up',
            'camera_local_axes':'+X right, +Y up, -Z forward','initial_camera_world':rows(vrpack.IDENTITY),
            'sample_hz':3840,'fps':60,'duration_key_span_seconds':68/60,'rows':samples}

def load(doc):
    data=json.dumps(doc).encode()
    return pair.load_camera_pair(data,expected_sidecar_sha256=hashlib.sha256(data).hexdigest(),
        candidate_sha256=doc['candidate_sha256'],action_fingerprints=doc['action_fingerprints'],
        native_start=0,native_end=68,fps=Fraction(60),candidate_frame_offset=1,
        frames=[Fraction(i,64) for i in range(4353)])

class R15AdmissionTests(unittest.TestCase):
    def test_full_grid_and_receipt(self):
        p=load(fixture());self.assertEqual(p.sample_hz,3840)
        self.assertEqual(p.delta_at(Fraction(1,64))[11],-1.26/4352)
        r=p.receipt(b'synthetic-vra','a'*64,pair.R15_RIG_ACTION)
        self.assertEqual(r['schema'],pair.R15_RECEIPT_SCHEMA)
        self.assertEqual(r['camera_sample_hz'],3840)
        self.assertEqual(r['source_camera_action'],pair.R15_CAMERA_ACTION)
    def test_wrong_identity_rejected_even_with_repaired_byte_hash(self):
        for kind in ('source','rig','camera'):
            d=fixture()
            if kind=='source':d['candidate_sha256']='b'*64
            else:d['action_fingerprints'][pair.R15_RIG_ACTION if kind=='rig' else pair.R15_CAMERA_ACTION]='b'*64
            with self.subTest(kind=kind),self.assertRaisesRegex(vrpack.AssetError,'exact approved'):load(d)
    def test_old_grid_cannot_be_relabelled_r15(self):
        d=fixture();d['rows']=d['rows'][::8]
        with self.assertRaisesRegex(vrpack.AssetError,'every sample'):load(d)
    def test_retimed_reordered_or_missing_samples_fail(self):
        for kind in ('time','frame','order','missing','rate'):
            d=fixture()
            if kind=='time':d['rows'][66]['time_seconds']+=.001
            elif kind=='frame':d['rows'][66]['candidate_frame']+=.001
            elif kind=='order':d['rows'][64],d['rows'][65]=d['rows'][65],d['rows'][64]
            elif kind=='missing':d['rows'].pop(55)
            else:d['sample_hz']=480
            with self.subTest(kind=kind),self.assertRaises(vrpack.AssetError):load(d)
    def test_unrelated_delta_is_not_accepted(self):
        d=fixture();d['rows'][50]['common_world_delta'][0][3]=.01
        with self.assertRaisesRegex(vrpack.AssetError,'differs'):load(d)
    def test_unknown_action_is_not_silently_admitted(self):
        with self.assertRaisesRegex(vrpack.AssetError,'unknown'):pair.action_names_for_clip('prone_future')
    def test_missing_subframe_cannot_be_interpolated_by_import_contract(self):
        p=load(fixture())
        with self.assertRaisesRegex(vrpack.AssetError,'no exact'):p.delta_at(Fraction(1,128))
    def test_nonfinite_camera_rejected(self):
        d=fixture();d['rows'][50]['camera_world'][0][0]=float('nan')
        with self.assertRaises(vrpack.AssetError):load(d)

if __name__=='__main__':unittest.main()
