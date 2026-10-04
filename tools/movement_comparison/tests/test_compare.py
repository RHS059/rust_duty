import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import compare as m


def fixture():
    doc={'schema':m.SCHEMA,'action':'synthetic-event','kind':'event','rubric_version':'event-amendment-pending',
        'source':{'artifact':{'name':'source.mp4','sha256':'0'*64},'viewport':[1280,720],'time_base':[1,15360],'window_frames':[100,112]},
        'candidate':{'artifact':{'name':'candidate.blend','sha256':'1'*64},'viewport':[1280,720],'space':'evaluated-camera-pixels','author':'synthetic author'},
        'registration':{'mode':'frozen-unwarped','source_scale':1,'candidate_scale':1,'source_anchor_pts':25600,'candidate_anchor_time':[0,1],'phase_offset':[0,1],'frozen_record':'synthetic fixture only'},
        'normalization':{'L_px':250,'definition':'synthetic fixed axis length'},'metrics_stride':3,'baseline_frame':100,
        'landmarks':[{'id':n,'physical_point':p} for n,p in [('muzzle','center of muzzle opening'),('receiver','top rear receiver corner'),('sight','top sight center')]],
        'axis_landmarks':['muzzle','receiver'],'samples':[],
        'events':[{'name':'dip','observation':'visible minimum, synthetic only','source_frame_interval':[105,106],'candidate_time_interval':[[5,60],[6,60]]}]}
    for f in range(100,112):
        points={n:{'xy':[x+(f-100)*2,y+(f-100)],'state':'visible','uncertainty_px':.1,'method':'synthetic known coordinates'} for n,(x,y) in zip(('muzzle','receiver','sight'),((100,100),(350,100),(325,80)))}
        doc['samples'].append({'frame':f,'source_pts':f*256,'candidate_time':[f-100,60],'reference':points,'candidate':copy.deepcopy(points)})
    return doc

class CompareTests(unittest.TestCase):
    def test_identical_has_no_score(self):
        r=m.compare(fixture());self.assertEqual(r['aggregate']['raw']['max'],0);self.assertIsNone(r['score']);self.assertFalse(r['artistic_approval']);self.assertFalse(r['provenance']['source']['bytes_verified'])
    def test_missing_frame_rejected(self):
        d=fixture();d['samples'].pop()
        with self.assertRaisesRegex(ValueError,'Every source frame'):m.compare(d)
    def test_phase_mapping_rejected(self):
        d=fixture();d['samples'][6]['candidate_time']=[5,60]
        with self.assertRaisesRegex(ValueError,'PTS mapping'):m.compare(d)
    def test_frozen_phase_supported(self):
        d=fixture();d['registration']['phase_offset']=[1,60]
        for r in d['samples']:r['candidate_time'][0]+=1
        self.assertEqual(m.compare(d)['metric_frame_count'],4)
    def test_duplicate_pts_rejected(self):
        d=fixture();d['samples'][1]['source_pts']=d['samples'][0]['source_pts']
        with self.assertRaisesRegex(ValueError,'PTS must'):m.compare(d)
    def test_source_mask_not_candidate_mask(self):
        d=fixture();d['samples'][0]['candidate']['muzzle']={'state':'missing','method':'no candidate sample'}
        r=m.compare(d);self.assertEqual(r['hard_gate_findings'][0]['frames'],[100]);self.assertEqual(r['landmarks']['muzzle']['coverage'],.75)
    def test_nonsampled_missing_candidate_retained(self):
        d=fixture();d['samples'][1]['candidate']['muzzle']={'state':'out_of_frame','method':'observed disappearance'}
        self.assertEqual(m.compare(d)['hard_gate_findings'][0]['frames'],[101])
    def test_occluded_source_unsupported(self):
        d=fixture()
        for r in d['samples']:r['reference']['muzzle']={'state':'occluded','method':'occluded in source'}
        r=m.compare(d);self.assertEqual(r['landmarks']['muzzle']['coverage'],0);self.assertIsNone(r['landmarks']['muzzle']['raw']);self.assertTrue(r['unsupported'])
    def test_uncertain_is_not_visible(self):
        d=fixture();d['samples'][0]['reference']['muzzle']['state']='uncertain'
        self.assertEqual(m.compare(d)['landmarks']['muzzle']['coverage'],.75)
    def test_prohibited_registration(self):
        for field,value in [('retiming',True),('framewise_shift',[]),('rotation',180)]:
            d=fixture();d['registration'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'registration prohibited'):m.compare(d)
    def test_framewise_shift_not_erased(self):
        d=fixture()
        for i,r in enumerate(d['samples']):
            for p in r['candidate'].values():p['xy'][1]+=i*i
        r=m.compare(d);self.assertGreater(r['aggregate']['mean_centered']['rms'],10);self.assertGreater(r['landmarks']['muzzle']['fixed_baseline_displacement']['error']['max'],50)
    def test_constant_shift_raw_retained(self):
        d=fixture()
        for r in d['samples']:
            for p in r['candidate'].values():p['xy'][0]+=20
        r=m.compare(d);self.assertAlmostEqual(r['aggregate']['raw']['rms'],20);self.assertEqual(r['aggregate']['mean_centered']['rms'],0)
    def test_degenerate_axis_not_pass(self):
        d=fixture()
        for r in d['samples']:r['candidate']['receiver']['xy']=r['candidate']['muzzle']['xy'][:]
        r=m.compare(d);self.assertTrue(r['axis']['degenerate_frames']);self.assertIsNone(r['axis']['raw_error_degrees'])
    def test_angle_wrapping(self):
        self.assertEqual(m.circular_delta(-179,179),2);self.assertEqual(m.unwrapped([179,-179,-175]),[179,181,185])
    def test_uncertainty_boundary_inconclusive(self):
        self.assertEqual(m.decision(14,16,15),'inconclusive');self.assertEqual(m.decision(0,15,15),'inconclusive')
    def test_uncertainty_not_automatic_pass(self):
        d=fixture()
        for r in d['samples']:
            for p in r['reference'].values():p['uncertainty_px']=20
        self.assertEqual(m.compare(d)['aggregate']['centered_uncertainty']['threshold_state'],'inconclusive')
    def test_nonfinite_rejected(self):
        for val in (float('nan'),float('inf'),True):
            d=fixture();d['samples'][0]['reference']['muzzle']['xy'][0]=val
            with self.subTest(val=val),self.assertRaises(ValueError):m.compare(d)
    def test_duplicate_json_rejected(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):m.strict_json(b'{"a":1,"a":2}')
    def test_same_point_mislabelling_rejected(self):
        d=fixture();d['axis_landmarks']=['muzzle','muzzle']
        with self.assertRaises(ValueError):m.compare(d)
    def test_missing_landmark_rejected(self):
        d=fixture();del d['samples'][0]['reference']['sight']
        with self.assertRaisesRegex(ValueError,'Every declared landmark'):m.compare(d)
    def test_missing_event_not_awarded(self):
        d=fixture();d['events'][0]['candidate_time_interval']=None
        self.assertIn('Candidate event missing: dip',m.compare(d)['unsupported'])
    def test_event_phase_interval(self):
        r=m.compare(fixture());self.assertEqual(r['events'][0]['phase_error_seconds_interval'],[-1/60,1/60])
    def test_artifact_bytes_verification(self):
        d=fixture();d['source']['artifact']['sha256']=m.sha256(b'video')
        self.assertTrue(m.compare(d,{'source.mp4':b'video'})['provenance']['source']['bytes_verified'])
        with self.assertRaisesRegex(ValueError,'hash mismatch'):m.compare(d,{'source.mp4':b'wrong'})
    def test_native_join_has_frame_index(self):
        r=m.compare(fixture());self.assertIn('from_frame',r['native_joins']['muzzle']['candidate']['largest_steps'][0])
    def test_third_anchor_area(self):
        r=m.compare(fixture());self.assertEqual(len(r['third_landmark_geometry']['sides']['reference']),12);self.assertNotEqual(r['third_landmark_geometry']['sides']['reference'][0]['signed_double_area_px2'],0)


class ReviewRegressions(unittest.TestCase):
    def test_disjoint_uncertain_extrema(self):
        d=fixture();selected=d['samples'][::3]
        for row,ax,au,bx,bu in zip(selected,[100,200,150,150],[5,5,0,0],[150,150,100,200],[0,0,5,5]):
            for side,x,u in [('reference',ax,au),('candidate',bx,bu)]:
                row[side]['muzzle']['xy'][0]=x;row[side]['muzzle']['uncertainty_px']=u
        r=m.compare(d)['landmarks']['muzzle']['amplitudes']['x']
        self.assertEqual(r['error_bound_px'],20);self.assertEqual(r['threshold_state'],'inconclusive')
    def test_single_sample_has_no_temporal_pass(self):
        d=fixture();d['metrics_stride']=60;r=m.compare(d)
        self.assertIsNone(r['landmarks']['muzzle']['mean_centered']);self.assertIsNone(r['landmarks']['muzzle']['amplitudes']);self.assertIsNone(r['axis']['centered_error_degrees'])
        self.assertEqual(r['aggregate']['centered_uncertainty']['threshold_state'],'unsupported');self.assertTrue(r['unsupported'])
    def test_collinear_third_anchor_unsupported(self):
        d=fixture()
        for row in d['samples']:
            for side in ('reference','candidate'):row[side]['sight']['xy']=row[side]['muzzle']['xy'][:]
        self.assertTrue(any('noncollinear' in x for x in m.compare(d)['unsupported']))
    def test_axis_gap_unsupported(self):
        d=fixture();d['samples'][3]['reference']['muzzle']['state']='occluded'
        self.assertIn('visibility gap',m.compare(d)['axis']['centered_status'])
    def test_ambiguous_branch_unsupported(self):
        import math
        d=fixture()
        for r,aa,ab in zip(d['samples'][::3],[0,179,178,177],[0,-179,178,177]):
            for side,a in [('reference',aa),('candidate',ab)]:
                r[side]['muzzle']['xy']=[200,200];r[side]['muzzle']['uncertainty_px']=0
                r[side]['receiver']['xy']=[200+100*math.cos(math.radians(a)),200+100*math.sin(math.radians(a))]
                r[side]['receiver']['uncertainty_px']=4 if side=='candidate' and a==-179 else 0
        r=m.compare(d)['axis'];self.assertAlmostEqual(r['raw_error_degrees']['rms'],1);self.assertIsNone(r['centered_error_degrees']);self.assertTrue(r['unwrap_unsupported_intervals'])
    def test_independent_pts_map(self):
        d=fixture();pts={'frames':[{'pts':i*256} for i in range(112)]}
        self.assertTrue(m.compare(d,decoded_pts=pts)['decoded_pts_witness']['verified_against_supplied_map'])
        pts['frames'][104]['pts']+=1
        with self.assertRaisesRegex(ValueError,'independently supplied'):m.compare(d,decoded_pts=pts)
    def test_native_coverage_cannot_hide_between_stride(self):
        d=fixture()
        for i,r in enumerate(d['samples']):
            if i%3:r['reference']['muzzle']['state']='occluded'
        r=m.compare(d)['landmarks']['muzzle'];self.assertEqual(r['coverage'],1);self.assertAlmostEqual(r['native_coverage']['comparable_over_planned'],1/3)
    def test_vfr_speed_witness_retained(self):
        d=fixture();d['source']['window_frames'][1]=115
        for i in range(12,15):
            row=copy.deepcopy(d['samples'][0]);row['frame']=100+i
            for side in ('reference','candidate'):
                for p in row[side].values():p['xy'][0]+=2*i
            d['samples'].append(row)
        for i,r in enumerate(d['samples']):
            pts=25600+i*256 if i<14 else 25600+13*256+1
            r['source_pts']=pts;r['candidate_time']=[pts-25600,15360]
        r=m.compare(d)['native_joins']['muzzle']['candidate'];self.assertEqual(r['largest_speeds'][0]['to_frame'],114);self.assertEqual(r['observed_adjacent_pairs'],14)
    def test_uncertain_third_anchor(self):
        d=fixture()
        for r in d['samples']:
            for side in ('reference','candidate'):
                for p in r[side].values():p['uncertainty_px']=25
        r=m.compare(d);self.assertTrue(any('noncollinear' in s for s in r['unsupported']))
    def test_phase_coverage(self):
        d=fixture();d['phases']=[{'name':'departure','window_frames':[100,106]}]
        d['samples'][0]['candidate']['muzzle']['state']='missing'
        phase=m.compare(d)['landmarks']['muzzle']['phase_coverage']['departure'];self.assertEqual(phase['source_visible'],6);self.assertEqual(phase['candidate_valid_when_source_visible'],5)
    def test_off_stride_axis_gap_is_unsupported(self):
        d=fixture();d['samples'][1]['reference']['muzzle']['state']='occluded'
        r=m.compare(d);self.assertTrue(r['axis']['unwrap_unsupported_intervals']);self.assertIsNone(r['axis']['centered_error_degrees'])
    def test_duplicate_phase_name_rejected(self):
        d=fixture();d['phases']=[{'name':'phase','window_frames':[100,104]},{'name':'phase','window_frames':[105,110]}]
        with self.assertRaisesRegex(ValueError,'Duplicate phase'):m.compare(d)
    def test_pts_timebase_mismatch_rejected(self):
        pts={'frames':[{'pts':i*256} for i in range(112)],'time_base':[1,1000]}
        with self.assertRaisesRegex(ValueError,'time base differs'):m.compare(fixture(),decoded_pts=pts)
    def test_pts_boolean_rejected(self):
        pts={'frames':[{'pts':i*256} for i in range(112)]};pts['frames'][100]['pts']=True
        with self.assertRaisesRegex(ValueError,'Invalid decoded map PTS'):m.compare(fixture(),decoded_pts=pts)

class UnsupportedNormalization(unittest.TestCase):
    def test_missing_L_keeps_raw_without_threshold_pass(self):
        d=fixture();d['normalization']['L_px']=None;r=m.compare(d)
        self.assertEqual(r['aggregate']['raw']['rms'],0)
        self.assertEqual(r['aggregate']['centered_uncertainty']['threshold_state'],'unsupported')
        self.assertEqual(r['landmarks']['muzzle']['amplitudes']['x']['threshold_state'],'unsupported')
        self.assertTrue(any('normalization L unavailable' in v for v in r['unsupported']))

if __name__=='__main__':unittest.main()
