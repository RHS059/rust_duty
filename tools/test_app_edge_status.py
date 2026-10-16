"""Static/status admission only. No native evidence or assets are generated."""
import copy,json,unittest
from pathlib import Path
import verify_app_edges as v
from app_edge_synthetic_fixture import make,BINDING,IDENTITY,CONTRACT
class SourceStatusTests(unittest.TestCase):
    def test_exact_real_source_status_now_passes_each_synthetic_case(self):
        for case in v.CASES:
            rows=make(case)
            self.assertTrue(all(r['visual']['warning']==v.REQUIRED_RENDER_STATUS for r in rows if 'visual' in r))
            self.assertTrue(v.validate(rows,BINDING,case,IDENTITY,CONTRACT)['journal_contract_validated'])
    def test_null_missing_empty_changed_appended_status_and_failure_reject(self):
        status=v.REQUIRED_RENDER_STATUS
        bad=[None,'',False,0,' ',status+' ',status+'\n',status.lower(),status+'; high mantle inactive: bad receipt',
            status+'; paired prone inactive: error',status+'; low vault inactive: error',status+'; Authored viewmodel playback failed: error',
            status.replace('fire, mantle','ADS, fire, mantle'),status.replace('; paired prone runtime remains opt-in WIP','')]
        for kind in ('app_frame','app_step'):
            for value in bad:
                rows=make('pause');next(r for r in rows if r['kind']==kind)['visual']['warning']=value
                with self.subTest(kind=kind,value=value),self.assertRaises(v.Rejected):v.validate(rows,BINDING,'pause',IDENTITY,CONTRACT)
            for failed in (True,False,0,None,'false'):
                if failed is False:continue
                rows=make('pause');next(r for r in rows if r['kind']==kind)['visual']['renderer_failed']=failed
                with self.subTest(kind=kind,failed=failed),self.assertRaises(v.Rejected):v.validate(rows,BINDING,'pause',IDENTITY,CONTRACT)
            rows=make('pause');next(r for r in rows if r['kind']==kind)['visual'].pop('warning')
            with self.assertRaises(KeyError):v.validate(rows,BINDING,'pause',IDENTITY,CONTRACT)
    def test_source_manifest_and_independent_review_identity_are_all_required(self):
        c=dict(source_root='candidate',source_files=[dict(path='candidate/src/authored_viewmodel.rs',sha256=v.STATUS_SOURCE_SHA256)],
            manifest=dict(sha256=v.STATUS_MANIFEST_SHA256))
        review=dict(renderer_status_contract=copy.deepcopy(v.STATUS_CONTRACT));v.check_source_status_identity(c,review)
        for field in ('source','manifest','review'):
            changed=copy.deepcopy(c);r=copy.deepcopy(review)
            if field=='source':changed['source_files'][0]['sha256']='f'*64
            elif field=='manifest':changed['manifest']['sha256']='f'*64
            else:r['renderer_status_contract']['required_status']='arbitrary warning'
            with self.subTest(field=field),self.assertRaises(v.Rejected):v.check_source_status_identity(changed,r)
        with self.assertRaises(v.Rejected):v.check_source_status_identity(c,{})
    def test_exact_source_derivation_and_rust_guards_are_pinned(self):
        prep=Path(__file__).absolute().parents[1]
        source=prep/'src/authored_viewmodel.rs'
        provenance=json.loads((prep/'tools/combined_source_contracts.json').read_text())
        self.assertEqual(v.sha(source),provenance['repository_renderer_sha256'])
        self.assertEqual(provenance['historical_native_renderer_sha256'],v.STATUS_SOURCE_SHA256)
        self.assertEqual(provenance['native_manifest_sha256'],v.STATUS_MANIFEST_SHA256)
        self.assertEqual(provenance['exact_required_real_visual_status'],v.REQUIRED_RENDER_STATUS)
        self.assertNotEqual(v.sha(source),v.STATUS_SOURCE_SHA256)
        candidate=dict(source_root='candidate',source_files=[dict(path='candidate/src/authored_viewmodel.rs',sha256=v.sha(source))],manifest=dict(sha256=v.STATUS_MANIFEST_SHA256))
        with self.assertRaises(v.Rejected):
            v.check_source_status_identity(candidate,dict(renderer_status_contract=copy.deepcopy(v.STATUS_CONTRACT)))
        text=(prep/'src/high_app_edge_input.rs').read_text();self.assertIn('pub const REQUIRED_RENDER_STATUS: &str = '+json.dumps(v.REQUIRED_RENDER_STATUS)+';',text)
        self.assertIn('!renderer_failed && warning == Some(REQUIRED_RENDER_STATUS)',text)
        capture=(prep/'src/high_app_edge_capture.rs').read_text()
        self.assertEqual(capture.count('!renderer_status_valid(model.warning(), model.error().is_some())'),2)
        self.assertNotIn('model.warning().is_some()',capture)
        self.assertLess(capture.index('!renderer_status_valid'),capture.index('trace::start_bounded'))
        self.assertIn('model.warning = Some(format!(',source.read_text())
if __name__=='__main__':unittest.main(verbosity=2)
