"""Source-only host/env regressions. No native, Blender, compiler or network work."""
import ast,builtins,contextlib,copy,ctypes,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import host_tools,orchestrate,prepare_controller,probe_blender,workflow_core as w

FIELDS=('system','release','version','machine')
OUTER={'system':'Windows','release':'2025Server','version':'10.0.26100','machine':'AMD64'}
NATIVE={**OUTER,'release':'11'}

def native_root():
    base=Path(__file__).absolute().parent.parent
    return next(base/name for name in ('native-producer-reviewed','windows-native-producer-v6') if (base/name/'host_identity.py').is_file())

def helper():
    return w.module('host_identity',native_root()/'host_identity.py',{})

class Environment(unittest.TestCase):
    def subset(self,value):
        with patch.object(prepare_controller.os,'environ',value):return prepare_controller.env_subset()
    def good(self):return {'SYSTEMROOT':'C:\\Windows','PATH':'C:\\Tools','PROCESSOR_ARCHITECTURE':'AMD64'}
    def test_exact_amd64_is_retained(self):
        result=self.subset(self.good());self.assertEqual(result['PROCESSOR_ARCHITECTURE'],'AMD64');self.assertNotIn('PROCESSOR_ARCHITEW6432',result)
    def test_optional_amd64_is_retained(self):
        result=self.subset({**self.good(),'PROCESSOR_ARCHITEW6432':'AMD64'});self.assertEqual(result['PROCESSOR_ARCHITEW6432'],'AMD64')
    def test_absent_architecture_fails_without_guessing(self):
        for value in ({'SYSTEMROOT':'C:\\Windows'},{'SYSTEMROOT':'C:\\Windows','PROCESSOR_ARCHITEW6432':'AMD64'}):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'architecture environment absent'):self.subset(value)
    def test_bad_architecture_fails(self):
        for value in ('','amd64','x86_64','ARM64','x86','AMD64 ','unknown',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'architecture environment unsupported'):self.subset({**self.good(),'PROCESSOR_ARCHITECTURE':value})
    def test_bad_optional_architecture_fails(self):
        for value in ('','amd64','ARM64','x86','unknown',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'architecture environment unsupported'):self.subset({**self.good(),'PROCESSOR_ARCHITEW6432':value})
    def test_noncanonical_architecture_key_fails(self):
        for key in ('processor_architecture','Processor_Architecture','processor_architew6432'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'architecture environment ambiguous'):self.subset({**self.good(),key:'AMD64'})
    def test_case_duplicate_allowed_key_fails(self):
        with self.assertRaisesRegex(ValueError,'architecture environment ambiguous'):self.subset({**self.good(),'Path':'other'})
    def test_overrides_are_filtered_without_replacement(self):
        forbidden=('PYTHONPATH','PYTHONHOME','BLENDER_USER_SCRIPTS','BLENDER_SYSTEM_SCRIPTS','VRVIEW_TOOLS_PATH','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','VR_WEAPON_ASSET')
        value={**self.good(),**{key:'private' for key in forbidden},'UNREVIEWED':'private'}
        result=self.subset(value);self.assertFalse(set(forbidden)&set(result));self.assertNotIn('UNREVIEWED',result)
        self.assertEqual(result['PATH'],value['PATH']);self.assertEqual(result['SYSTEMROOT'],value['SYSTEMROOT'])
    def test_fixed_behavior_stays_exact(self):
        result=self.subset({**self.good(),'PYTHONDONTWRITEBYTECODE':'0','PYTHONNOUSERSITE':'0','CARGO_TERM_COLOR':'always','CI':'false'})
        self.assertEqual({k:result[k] for k in ('PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','CARGO_TERM_COLOR','CI')},{'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','CARGO_TERM_COLOR':'never','CI':'true'})
    def test_system_environment_still_required(self):
        with self.assertRaisesRegex(ValueError,'Windows system environment absent'):self.subset({'PROCESSOR_ARCHITECTURE':'AMD64'})

class Probe(unittest.TestCase):
    def observe(self,host=NATIVE,platform='win32',width=8):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(probe_blender.sys,'platform',platform));stack.enter_context(patch.object(probe_blender.ctypes,'sizeof',return_value=width))
            for key in FIELDS:stack.enter_context(patch.object(probe_blender.platform,key,return_value=host.get(key)))
            return probe_blender.observe_host()
    def test_exact_native_platform_observation(self):self.assertEqual(self.observe(),NATIVE)
    def test_missing_empty_unknown_observation_fails(self):
        for field in FIELDS:
            for value in (None,'',' ','unknown','Unknown','x'*129,'a\0b'):
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.observe({**NATIVE,field:value})
    def test_invalid_release_and_version_fail(self):
        for field,value in (('release','2025 Server'),('release','_11'),('version','10.0'),('version','10.0.26100.extra'),('version','10.0.26100 ')):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.observe({**NATIVE,field:value})
    def test_machine_aliases_and_wrong_system_fail(self):
        for field,value in (('system','Linux'),('system','windows'),('machine','x86_64'),('machine','ARM64'),('machine','amd64')):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.observe({**NATIVE,field:value})
    def test_nonwin32_and_32bit_fail(self):
        for platform,width in (('linux',8),('win32',4)):
            with self.subTest(platform=platform,width=width),self.assertRaises(ValueError):self.observe(platform=platform,width=width)
    def test_source_import_does_not_import_blender(self):
        source=ast.parse((w.HERE/'probe_blender.py').read_bytes())
        for node in source.body:
            if isinstance(node,ast.Import):self.assertFalse({'bpy','io_scene_fbx'}&{name.name for name in node.names})
    def test_schema_and_safe_read_proof_flags_are_explicit(self):
        text=(w.HERE/'probe_blender.py').read_text();self.assertIn('rust-duty-official-blender-host-observation/v2',text)
        self.assertIn("'observed_host':observed_host",text);self.assertIn("'sys_platform':sys.platform",text);self.assertIn("'pointer_bits':ctypes.sizeof(ctypes.c_void_p)*8",text)
        self.assertNotIn('bpy.ops.render',text);self.assertNotIn('bpy.ops.wm.save',text)

class Collection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.candidate=self.root/'private/session/candidates/candidate'
        self.bundle=self.root/'blender';self.exe=self.put('blender/blender.exe',b'blender');self.runtime=self.put('blender/python311.dll',b'embedded DLL')
        self.python=self.put('outer/python.exe',b'outer Python');self.outer_runtime=self.put('outer/python313.dll',b'outer DLL');self.install=self.put('install.json',b'{}')
        self.embedded=self.put('blender/4.3/python/bin/python.exe',b'embedded Python');self.put('blender/4.3/python/lib/site-packages/pillow.py',b'pillow')
        self.addon=self.put('blender/scripts/addons_core/io_scene_fbx/__init__.py',b'fbx');self.put('blender/scripts/addons_core/io_scene_gltf2/__init__.py',b'gltf')
        self.config={'roots':{'blender_bundle':str(self.bundle),'context_package':str(self.root/'context')},'blender_install_receipt':str(self.install),'runner_id':'runner','run_id':'run','native_environment':{'SYSTEMROOT':'C:\\Windows','PROCESSOR_ARCHITECTURE':'AMD64'},'candidate_id':'candidate','session_id':'session','pins':{'context':'a'*64,'producer':'b'*64}}
        self.observation={'schema':'rust-duty-official-blender-host-observation/v2','observed_host':dict(NATIVE),'sys_platform':'win32','pointer_bits':64,'blender_version':[4,3,2],'blender_build_hash':'fixture','blender_binary':str(self.exe),'blender_binary_sha256':w.sha(self.exe),'python_runtime':str(self.runtime),'python_runtime_sha256':w.sha(self.runtime),'fbx_addon_file':str(self.addon),'background':True,'autoexec_disabled':True,'source_saved':False,'rendered':False}
        self.identity=helper();self.calls=[];self.constructors=[]
    def tearDown(self):self.temp.cleanup()
    def put(self,path,value):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value);return target
    def collect(self,observation=None,outer=OUTER):
        def run(label,argv,cwd,**kwargs):
            self.calls.append((label,argv,cwd,kwargs));terminal=w.write_new(self.candidate/'process'/label/'terminal.json',{'synthetic':True})
            context=w.write_new(self.candidate/'contexts'/(label+'-command.json'),{'synthetic':True})
            if label=='blender-host-observation':w.write_new(self.candidate/'blender-observed.json',self.observation if observation is None else observation)
            return {'context':context,'terminal':terminal}
        def commands(*args,**kwargs):self.constructors.append((args,kwargs));return N(run=run)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(host_tools.sys,'platform','win32'));stack.enter_context(patch.object(host_tools.sys,'executable',str(self.python)))
            stack.enter_context(patch.object(host_tools.ctypes,'sizeof',return_value=8))
            for key in FIELDS:stack.enter_context(patch.object(host_tools.platform,key,return_value=outer[key]))
            stack.enter_context(patch.object(host_tools,'verify_install',return_value={}));stack.enter_context(patch.object(host_tools,'python_runtime',return_value=self.outer_runtime))
            stack.enter_context(patch.object(host_tools,'module',return_value=N(resolve_addon=lambda *a:None,PIN_FILE_SHA='c'*64)))
            stack.enter_context(patch.object(host_tools,'Commands',side_effect=commands))
            return host_tools.collect(self.config,N(digest=lambda value:w.digest({'transport':value})),None,self.candidate,'validator',self.identity)
    def test_collection_retains_role_specific_host_and_owned_probe(self):
        host,binding,_=self.collect();manifest=w.strict_json(binding['path'])
        self.assertEqual(manifest['schema'],'rust-duty-windows-native-host/v3');self.assertEqual(manifest['observed_host'],OUTER);self.assertEqual(manifest['native_observed_host'],NATIVE)
        self.assertEqual(manifest['native_observation'],{'probe':w.file_pin(self.candidate/'blender-observed.json'),'command_context':w.file_pin(self.candidate/'contexts/blender-host-observation-command.json'),'process_terminal':w.file_pin(self.candidate/'process/blender-host-observation/terminal.json'),'probe_source':w.file_pin(w.HERE/'probe_blender.py')})
        self.assertEqual(manifest['runner_id'],'runner');self.assertEqual(manifest['run_id'],'run');self.assertEqual(manifest['candidate_id'],'candidate');self.assertEqual(manifest['session_id'],'session');self.assertEqual(host['build_sha256'],w.sha(binding['path']))
        self.assertEqual(manifest['controller_environment_sha256'],w.digest(self.config['native_environment']))
        self.assertEqual(manifest['native_environment_sha256'],w.digest({'transport':self.config['native_environment']}))
    def test_collection_keeps_same_executable_runtime_environment(self):
        _,binding,_=self.collect();value=w.strict_json(binding['path']);self.assertEqual(value['tools']['blender'],w.file_pin(self.exe));self.assertEqual(value['tools']['blender_python_runtime'],w.file_pin(self.runtime))
        argv=self.calls[-1][1];self.assertEqual(argv,[str(self.exe),'--background','--factory-startup','--disable-autoexec','--threads','1','--python-exit-code','1','--python',str(w.HERE/'probe_blender.py'),'--',str(self.candidate/'blender-observed.json')])
        for args,kwargs in self.constructors:self.assertIs(args[3],self.config['native_environment']);self.assertEqual(args[4],'validator')
    def test_cross_role_version_rejection_does_not_write_binding(self):
        value=copy.deepcopy(self.observation);value['observed_host']['version']='10.0.99999'
        with self.assertRaisesRegex(ValueError,'cross-role host version differs'):self.collect(value)
        self.assertFalse((self.candidate/'host-binding.json').exists())
    def test_missing_extra_probe_fields_and_old_schema_reject(self):
        for mutation in (lambda v:v.pop('observed_host'),lambda v:v.update(extra='private'),lambda v:v.update(schema='rust-duty-official-blender-host-observation/v1')):
            value=copy.deepcopy(self.observation);mutation(value)
            with self.subTest(value=value),self.assertRaises(ValueError):host_tools.validate_probe(value,OUTER,self.exe,self.identity)
    def test_invalid_platform_or_pointer_shape_rejects(self):
        for field,value in (('sys_platform','linux'),('pointer_bits',32),('pointer_bits','64'),('pointer_bits',True)):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):host_tools.validate_probe({**self.observation,field:value},OUTER,self.exe,self.identity)
    def test_invalid_observed_host_rejects(self):
        for value in ({**NATIVE,'extra':'private'},{k:v for k,v in NATIVE.items() if k!='machine'},{**NATIVE,'release':''},{**NATIVE,'machine':'x86_64'}):
            with self.subTest(value=value),self.assertRaises(ValueError):host_tools.validate_probe({**self.observation,'observed_host':value},OUTER,self.exe,self.identity)
    def test_tool_bytes_and_unsafe_probe_actions_reject(self):
        for field,value in (('blender_binary_sha256','f'*64),('python_runtime_sha256','f'*64),('source_saved',True),('rendered',True),('autoexec_disabled',False),('background',False)):
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):host_tools.validate_probe({**self.observation,field:value},OUTER,self.exe,self.identity)
    def test_invalid_outer_host_rejects_before_any_command(self):
        with self.assertRaises(ValueError):self.collect(outer={**OUTER,'machine':''})
        self.assertEqual(self.calls,[])

class Loader(unittest.TestCase):
    def test_native_helper_load_order_is_before_consumers(self):
        tree=ast.parse((w.HERE/'orchestrate.py').read_bytes());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='modules']
        names=next(ast.literal_eval(call.args[1]) for call in calls if 'native_producer' in ast.unparse(call.args[0]))
        self.assertLess(names.index('host_identity'),names.index('stage_context'));self.assertLess(names.index('host_identity'),names.index('admission'))
    def test_actual_native_modules_do_not_use_ambient_helper(self):
        tree=ast.parse((w.HERE/'orchestrate.py').read_bytes());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='modules']
        names=next(ast.literal_eval(call.args[1]) for call in calls if 'native_producer' in ast.unparse(call.args[0]))
        real=builtins.__import__;trapped=[]
        def importer(name,*args,**kwargs):
            if name=='host_identity':trapped.append(name);raise AssertionError('ambient host helper import')
            return real(name,*args,**kwargs)
        with patch.object(builtins,'__import__',side_effect=importer):loaded=w.modules(native_root(),names)
        self.assertEqual(trapped,[]);self.assertEqual(loaded.host_identity.validate_observed_host(NATIVE),NATIVE)
        self.assertIs(loaded.admission.require_native_host,loaded.host_identity.require_native_host)

if __name__=='__main__':unittest.main(verbosity=2)
