"""CPU regressions for the exact transport boundary; no native/process launch."""
import ast,contextlib,copy,dataclasses,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import command_contract,host_tools,owned_commands,workflow_core as w

ERROR_SHA='255c614ba75ddc6ba26bcb310ffa6f021ee9b7f27be300370ae5faa1974b8587'

class CommandContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=w.HERE.parent
        adapter=base/'process-v2';producer=base/'native-producer-reviewed'
        if not adapter.exists():
            adapter=base/'windows-process-adapter-v2';producer=base/'windows-native-producer-v4'
        cls.adapter,cls.evidence=command_contract.load_dependencies(adapter,producer)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.candidate=self.root/'session/candidates/synthetic';self.candidate.mkdir(parents=True)
        self.python=self.root/'synthetic-python.exe';self.python.write_bytes(b'nonexecuted fixture')
        self.python_patch=patch.object(sys,'executable',str(self.python));self.python_patch.start()
        self.host={'runner_id':'synthetic','run_id':'contract','build_sha256':'a'*64,
                   'system':'Windows','release':'synthetic','version':'synthetic','machine':'AMD64'}
        self.environment={'SystemRoot':'C:\\Windows','contract_value':'space and Unicode é'}
    def tearDown(self):self.python_patch.stop();self.temp.cleanup()

    def command(self,mutation=None):
        seen={}
        @contextlib.contextmanager
        def run(argv,cwd,limits,target,binding):
            target.mkdir();(target/'stdout.bin').write_bytes(b'');(target/'stderr.bin').write_bytes(b'')
            record={'completed':True,'windows_job_empty_verified':True,'command':argv,'cwd':str(cwd),'host_binding':binding.record()}
            if mutation:mutation(record)
            w.write_new(target/'terminal.json',record);seen.update(record=record,binding=binding,limits=limits)
            yield N(wait=lambda:None)
        def validate(adapter,target,expected):
            seen['expected']=expected
            self.evidence.exact(seen['record']['host_binding'],expected['host_binding'],'process host_binding')
        adapter=N(HostBinding=self.adapter.HostBinding,Limits=self.adapter.Limits,digest=self.adapter.digest,
                  OwnedProcess=N(run=run),verify_attempt=lambda *a,**k:seen['record'])
        result=owned_commands.Commands(adapter,self.host,self.candidate,self.environment,validate).run(
            'synthetic',[sys.executable,'-I','-B','-c','pass'],self.candidate)
        return seen,result

    def test_exact_ci_error_is_original_semantic_validator_message(self):
        with self.assertRaises(ValueError) as caught:
            self.evidence.exact({'environment_sha256':self.adapter.digest(self.environment)},
                                {'environment_sha256':w.digest(self.environment)},'process host_binding')
        self.assertEqual(hashlib.sha256(str(caught.exception).encode()).hexdigest(),ERROR_SHA)

    def test_newline_is_the_exact_protocol_difference(self):
        raw=json.dumps(self.environment,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        self.assertEqual(w.digest(self.environment),hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.adapter.digest(self.environment),hashlib.sha256(raw+b'\n').hexdigest())
        self.assertNotEqual(w.digest(self.environment),self.adapter.digest(self.environment))

    def test_commands_expected_binding_matches_unchanged_adapter_record(self):
        seen,result=self.command()
        self.assertEqual(seen['expected']['host_binding'],seen['binding'].record())
        self.assertEqual(result['environment_sha256'],w.digest(self.environment))
        self.assertEqual(seen['limits'].rss_bytes,3*1024**3)
        self.assertEqual(seen['limits'].disk_floor_bytes,1024**3)
        self.assertEqual((seen['limits'].sample_seconds,seen['limits'].deadline_seconds),(.2,1800.))

    def test_original_wrong_encoding_reproduces_ci_before_next_command(self):
        old=lambda adapter,env:{'environment_sha256':w.digest(env),'environment_keys':sorted(env)}
        with patch.object(owned_commands,'transport_environment_binding',side_effect=old):
            with self.assertRaises(ValueError) as caught:self.command()
        self.assertEqual(hashlib.sha256(str(caught.exception).encode()).hexdigest(),ERROR_SHA)

    def test_changed_transport_fingerprint_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'process host_binding differs'):
            self.command(lambda r:r['host_binding'].update(environment_sha256='f'*64))

    def test_context_fingerprint_remains_controller_encoding(self):
        seen,_=self.command();raw=w.strict_json(self.candidate/'contexts/synthetic-command.json')
        self.assertEqual(seen['binding'].context_sha256,w.digest(raw))
        self.assertNotEqual(seen['binding'].context_sha256,self.adapter.digest(raw))

    def test_controller_and_build_implementations_are_byte_unchanged(self):
        self.assertEqual(w.sha(w.HERE/'workflow_core.py'),'e5bae5b323ca1503f1fb6851f9d90cc98d452b137aaf5810af5c3fcddec30428')
        self.assertEqual(w.sha(w.HERE/'build_rust.py'),'bb1d213030a427133b852410d629df9128c8ceb127846322f0528177454caf1b')

    def test_host_collection_uses_transport_protocol_for_native_binding(self):
        bundle=self.root/'blender';embedded=bundle/'4.3/python/bin/python.exe';embedded.parent.mkdir(parents=True);embedded.write_bytes(b'python')
        exe=bundle/'blender.exe';exe.write_bytes(b'blender');(bundle/'x.dll').write_bytes(b'dll')
        site=bundle/'4.3/python/lib/site-packages';site.mkdir(parents=True);(site/'pillow.py').write_bytes(b'original')
        addon=bundle/'scripts/addons_core/io_scene_fbx';addon.mkdir(parents=True);(addon/'__init__.py').write_bytes(b'addon')
        gltf=addon.parent/'io_scene_gltf2';gltf.mkdir();(gltf/'__init__.py').write_bytes(b'gltf')
        receipt=self.root/'install.json';receipt.write_bytes(b'{}')
        config={'roots':{'blender_bundle':str(bundle),'context_package':str(self.root/'context')},
                'blender_install_receipt':str(receipt),'runner_id':'synthetic','run_id':'contract',
                'native_environment':self.environment,'candidate_id':'synthetic','session_id':'session',
                'pins':{'context':'a'*64,'producer':'b'*64}}
        def fake_run(label,argv,cwd,**kwargs):
            terminal=self.candidate/'process'/label/'terminal.json';w.write_new(terminal,{'synthetic':True})
            if label=='blender-host-observation':
                w.write_new(self.candidate/'blender-observed.json',{'blender_version':[4,3,2],
                    'blender_binary_sha256':w.sha(exe),'blender_binary':str(exe),'source_saved':False,'rendered':False,
                    'fbx_addon_file':str(addon/'__init__.py'),'python_runtime':str(embedded),'blender_build_hash':'synthetic'})
            return {}
        resolver=N(resolve_addon=lambda *a:None,PIN_FILE_SHA='c'*64)
        with patch.object(host_tools.sys,'platform','win32'),patch.object(host_tools.platform,'system',return_value='Windows'),\
             patch.object(host_tools,'verify_install',return_value={}),patch.object(host_tools,'python_runtime',return_value=embedded),\
             patch.object(host_tools,'module',return_value=resolver),patch.object(host_tools,'Commands',return_value=N(run=fake_run)):
            _,binding,_=host_tools.collect(config,self.adapter,None,self.candidate,None)
        host=w.strict_json(binding['path'])
        self.assertEqual(host['native_environment_sha256'],self.adapter.digest(self.environment))
        self.assertEqual(host['native_environment_keys'],sorted(self.environment))
        self.assertNotEqual(host['native_environment_sha256'],w.digest(self.environment))

    def test_windows_leaf_regression_uses_authoritative_verifier(self):
        source=(w.HERE/'command_contract.py').read_text()
        self.assertIn('evidence.verify_completed_process',source)
        self.assertIn("sys.executable,'-I','-B','-c'",source)
        self.assertNotIn('blender.exe',source)
        self.assertNotIn('cargo',source.lower())

    def test_active_workflow_runs_leaf_contract_before_native_installers(self):
        source=(w.HERE/'onehand-windows-proof.yml').read_text()
        self.assertLess(source.index("'command_contract.py'"),source.index('Verify official vendor checksum and install Blender and Rust'))
        self.assertIn('/source-evidence/command-contract.json',source)
        self.assertNotIn('/command-contract/session/',source)

if __name__=='__main__':unittest.main()
