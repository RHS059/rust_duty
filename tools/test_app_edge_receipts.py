"""Invented byte-pinned receipts exercise admission parsing only; no Rust or native execution."""
import copy, json, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from verify_app_edges import (verify_config, sha, digest, Rejected, candidate_identity,
    RUST_CHECKS, RUST_TESTS, rust_environment)

class ReceiptFixture:
    def __init__(self,root):
        self.root=root
        source=self.file('source/example.rs','// Invented, never compiled.\n')
        inventory=[source];source_fp=digest(inventory)
        allow=self.file('allow.json',dict(schema='rust-duty-app-edge-overlay/v1',unapplied=True,files=[dict(path='example.rs',sha256=source['sha256'])]))
        binary=self.file('never-executed.txt','Invented binary identity; never executable.\n')
        receipt=self.file('high-receipt.json',{'synthetic_only':True});asset=self.file('high.vra','Invented bytes, not a game asset.\n')
        companions={s:self.file('high.'+s,'Invented companion.\n') for s in ('vrs','vrm')}
        manifest=self.file('manifest.cfg','Invented manifest.\n');settings=self.file('settings.cfg','Invented settings.\n')
        payload=[receipt,asset,*companions.values(),manifest,settings]
        review=self.file('review.json',dict(passed=True,app_edge_overlay_sha256=allow['sha256'],source_fingerprint=source_fp,
            package_identity='invented-cpu-fixture',high_receipt_sha256=receipt['sha256'],high_asset_sha256=asset['sha256'],payload_fingerprint=digest(sorted(payload,key=lambda r:r['path']))))
        self.config=dict(schema='rust-duty-app-edge-run-contract/v1',admitted=True,root=str(root),recipe='high-onto-app-input-edges/v1',
            cases=['pause','reset','debug-death'],independent_review=review,overlay_allowlist=allow,source_root='source',source_files=inventory,
            source_fingerprint=source_fp,package_identity='invented-cpu-fixture',binary=binary,build_version='SYNTHETIC',build_number=1,
            high_receipt=receipt,high_asset=asset,high_companions=companions,binding=dict(receipt_sha256=receipt['sha256'],asset_sha256=asset['sha256'],return_seconds=.2),
            payload_files=payload,manifest=manifest,settings=settings,runtime='legacy',renderer='gl',run_id='invented-cpu-fixture',
            rust_target_dir=str(root/'never-used-target'),native_focus_supported=False)
        self.receipt=dict(schema='rust-duty-app-edge-rust-checks/v1',candidate=candidate_identity(self.config),completed=True,exit_code=0,
            rust_format_passed=True,rust_tests_passed=True,runtime_checks_passed=True,checks=[])
        for name,cmd,seconds in RUST_CHECKS:
            log='Invented result, not execution.\n'
            if name=='lib_tests':log+='running '+str(len(RUST_TESTS))+' tests\n'+'\n'.join('test '+t+' ... ok' for t in RUST_TESTS)+'\ntest result: ok. '+str(len(RUST_TESTS))+' passed; 0 failed; 0 ignored; 0 measured; 999 filtered out; finished in 0.00s\n'
            self.receipt['checks'].append(dict(name=name,**self.command(cmd,self.file(name+'.log',log))))
        cmd=['cargo','build','--offline','--no-default-features','--features','legacy-macroquad','--bin','vector-range']
        self.build=dict(schema='rust-duty-app-edge-build-receipt/v1',source_fingerprint=source_fp,binary=binary,overlay_allowlist_sha256=allow['sha256'],
            candidate=candidate_identity(self.config),build_version='SYNTHETIC',build_number=1,rust_format_passed=True,rust_tests_passed=True,runtime_checks_passed=True,
            **self.command(cmd,self.file('build.log','Invented result, no build performed.\n')))
    def command(self,cmd,log):
        c=self.config
        return dict(command=cmd,cwd=str(self.root/'source'),environment=rust_environment(c),completed=True,exit_code=0,timed_out=False,
            process_group_terminal=True,wall_seconds=1.,source_before_fingerprint=c['source_fingerprint'],source_after_fingerprint=c['source_fingerprint'],
            resource_observation=dict(live_guard_active=True,guard_triggered=False,minimum_free_bytes=1288490189,
                minimum_memory_available_bytes=2147483648,maximum_new_target_bytes=0),log=log)
    def file(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(value if isinstance(value,str) else json.dumps(value,sort_keys=True))
        return dict(path=name,bytes=p.stat().st_size,sha256=sha(p))
    def verify(self):
        self.build['rust_checks_receipt']=self.file('checks.json',self.receipt)
        self.config['build_receipt']=self.file('build.json',self.build)
        pin=self.file('contract.json',self.config)
        # This isolated receipt parser fixture has invented source/manifest
        # bytes, so it cannot satisfy real source-status admission. Test that
        # separate gate independently; never use this fixture as native evidence.
        with patch('verify_app_edges.check_source_status_identity'):
            return verify_config(self.root/pin['path'],pin['sha256'])

class RustReceiptTests(unittest.TestCase):
    def test_complete_invented_receipt_parses_but_is_not_native_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            f=ReceiptFixture(Path(d));c,*_=f.verify();self.assertEqual(c['run_id'],'invented-cpu-fixture')
    def reject(self,change):
        with tempfile.TemporaryDirectory() as d:
            f=ReceiptFixture(Path(d));change(f)
            with self.assertRaises((Rejected,KeyError,TypeError,ValueError)):f.verify()
    def test_failed_nonterminal_or_contradictory_check_receipt(self):
        for label,value in [('schema','wrong'),('completed',False),('exit_code',1),('exit_code',False),('rust_format_passed',False),('rust_tests_passed',False),('runtime_checks_passed',False)]:
            with self.subTest(label=label,value=value):self.reject(lambda f:f.receipt.update({label:value}))
        self.reject(lambda f:f.receipt.update(completed=False,exit_code=1,rust_format_passed=False,rust_tests_passed=False,runtime_checks_passed=False))
        self.reject(lambda f:f.receipt.update(unexpected=True))
        for field in ('rust_format_passed','rust_tests_passed','runtime_checks_passed'):
            with self.subTest(build_flag=field):self.reject(lambda f:f.build.update({field:False}))
    def test_missing_duplicate_reordered_or_wrong_commands_fail(self):
        for mode in ('missing','duplicate','reorder'):
            def change(f):
                if mode=='missing':f.receipt['checks'].pop()
                elif mode=='duplicate':f.receipt['checks'].append(copy.deepcopy(f.receipt['checks'][0]))
                else:f.receipt['checks'].reverse()
            with self.subTest(mode=mode):self.reject(change)
        for i in range(4):
            for field,value in [('command',['cargo','check']),('cwd','/wrong'),('environment',{}),('completed',False),('exit_code',1),
                ('timed_out',True),('process_group_terminal',False),('wall_seconds',601.),('source_before_fingerprint','f'*64),('source_after_fingerprint','f'*64)]:
                with self.subTest(index=i,field=field):self.reject(lambda f:f.receipt['checks'][i].update({field:value}))
    def test_candidate_identity_includes_complete_source_payload_backend_and_review(self):
        for key in ('source_root','source_files','source_fingerprint','overlay_allowlist','package_identity','independent_review','high_receipt',
            'high_asset','high_companions','binding','payload_files','manifest','settings','runtime','renderer','build_version','build_number','rust_target_dir','native_focus_supported'):
            with self.subTest(key=key):self.reject(lambda f:f.receipt['candidate'].update({key:None}))
        self.reject(lambda f:f.build['candidate'].update(runtime='wgpu'))
    def test_resource_guards_logs_and_actual_test_results_required(self):
        for field,value in [('live_guard_active',False),('guard_triggered',True),('minimum_free_bytes',1073741824),
            ('minimum_memory_available_bytes',1),('maximum_new_target_bytes',402653185)]:
            with self.subTest(field=field):self.reject(lambda f:f.receipt['checks'][0]['resource_observation'].update({field:value}))
        self.reject(lambda f:f.receipt['checks'][1].update(log=f.receipt['checks'][0]['log']))
        self.reject(lambda f:(f.root/'fmt.log').write_text('Changed after pin.'))
        for text in ('No actual tests in this synthetic log.\n','\n'.join('test '+t+' ... ok' for t in RUST_TESTS)+'\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 999 filtered out; finished in 0.00s\n'):
            with self.subTest(text=text):self.reject(lambda f:f.receipt['checks'][1].update(log=f.file('lib_tests.log',text)))
    def test_384_mib_cumulative_resource_boundary_is_fixed_for_checks_and_build(self):
        # One shared gate baseline; never reset this reservation per command.
        for used in (268435456,268435457,402653184):
            with self.subTest(accepted=used),tempfile.TemporaryDirectory() as d:
                f=ReceiptFixture(Path(d))
                for entry in [*f.receipt['checks'],f.build]:
                    entry['resource_observation']['maximum_new_target_bytes']=used
                f.verify()
        for index in range(5):
            for used in (402653185,-1,True,402653184.0):
                def change(f):
                    entries=[*f.receipt['checks'],f.build]
                    entries[index]['resource_observation']['maximum_new_target_bytes']=used
                with self.subTest(index=index,rejected=used):self.reject(change)
    def test_original_appended_failed_test_and_summary_repros_reject(self):
        for extra in ('test unrelated::failure ... FAILED\n',
            'test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured; 999 filtered out; finished in 0.00s\n',
            'test unrelated::extra ... ok\n','failures:\n','error: test failed\n'):
            with self.subTest(extra=extra):
                self.reject(lambda f:f.receipt['checks'][1].update(log=f.file('lib_tests.log',(f.root/'lib_tests.log').read_text()+extra)))
    def test_original_unlisted_source_directory_symlink_repro_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            f=ReceiptFixture(Path(d));f.verify();pin=sha(f.root/'contract.json')
            extra=f.root/'untracked-input';extra.mkdir();(extra/'extra.rs').write_text('// Invented untracked source.\n')
            (f.root/'source/linked').symlink_to(extra,target_is_directory=True)
            with patch('verify_app_edges.check_source_status_identity'):
                with self.assertRaisesRegex(Rejected,'source tree contains symlink'):
                    verify_config(f.root/'contract.json',pin)
    def test_original_reviewer_failed_receipt_reproducer_is_rejected(self):
        # Preserve the original reviewer's invented failed receipt locally.
        # Require the receipt-schema rejection, not an unrelated path/import error.
        from app_edge_review_fixture import failed_rust_receipt
        with self.assertRaisesRegex(Rejected,'Rust checks receipt schema fields'):
            failed_rust_receipt()

    def test_original_reviewer_fixture_preserves_failed_nonterminal_receipt(self):
        from app_edge_review_fixture import failed_rust_receipt
        def inspect(config_path,config_pin):
            self.assertEqual(sha(config_path),config_pin)
            config=json.loads(config_path.read_text());root=config_path.parent
            build=json.loads((root/config['build_receipt']['path']).read_text())
            ref=build['rust_checks_receipt'];path=root/ref['path']
            self.assertEqual(sha(path),ref['sha256'])
            self.assertEqual(path.stat().st_size,ref['bytes'])
            self.assertEqual(json.loads(path.read_text()),dict(completed=False,exit_code=1,
                rust_tests_passed=False,runtime_checks_passed=False,rust_format_passed=False,
                note='Deliberately failed/nonterminal checks.'))
        with patch('app_edge_review_fixture.verify_config',side_effect=inspect) as verifier:
            result=failed_rust_receipt()
        verifier.assert_called_once()
        self.assertEqual(result,dict(admission_accepted=True,checks_receipt_completed=False,
            checks_receipt_exit_code=1,checks_receipt_all_pass_flags=False))

if __name__=='__main__':unittest.main(verbosity=2)
