"""Synthetic Windows-profile mutations; no addon imports or native execution."""
import copy,json,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).absolute().parent))
from test_observe_official_addon import Fixture,write_json
import observe_official_addon as o

class WindowsProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.f=Fixture(Path(self.temp.name).absolute())
        self.original=json.loads((self.f.context/'OFFICIAL_ADDON_PINS.json').read_bytes())
    def rewrite(self,value):
        path=self.f.context/'OFFICIAL_ADDON_PINS.json';write_json(path,value)
        self.f.patches['ADDON_PINS_SHA']=o.sha(path.read_bytes())
        manifest=self.f.context/'PINS.json';write_json(manifest,{'OFFICIAL_ADDON_PINS.json':self.f.patches['ADDON_PINS_SHA']})
        self.f.patches['CONTEXT_PINS_SHA']=o.sha(manifest.read_bytes())
    def pins(self):
        with mock.patch.multiple(o,**self.f.patches):return o.addon_pins(self.f.context)
    def reject(self,mutate,code=None):
        value=copy.deepcopy(self.original);mutate(value);self.rewrite(value)
        with self.assertRaisesRegex(o.ObservationError,code or '.'):
            self.pins()
    def test_valid_windows_raw_profile_matches_installed_crlf(self):
        pins=self.pins();self.assertEqual(set(pins),o.NAMES)
        self.assertEqual(pins,{name:o.sha(raw) for name,raw in self.f.members.items()})
        self.assertTrue(all(pins[name]!=o.sha(raw) for name,raw in self.f.expected.items()))
    def test_raw_and_loaded_function_domains_remain_distinct(self):
        self.assertNotEqual(self.original['raw_functions_sha256'],self.original['loaded_functions_sha256'])
        self.assertEqual(self.pins(),self.original['files'])
    def test_original_linux_schema_and_functions_field_rejected(self):
        self.reject(lambda v:v.update(schema='rust-duty-logical-official-fbx-pins/v1'),'addon_pin_contract_differs')
        self.reject(lambda v:v.update(functions=v['loaded_functions_sha256']),'json_fields_differ')
    def test_missing_or_extra_top_level_fields_rejected(self):
        for key in self.original:
            with self.subTest(key=key):self.reject(lambda v:v.pop(key),'json_fields_differ')
        self.reject(lambda v:v.update(unreviewed=True),'json_fields_differ')
    def test_profile_id_and_version_mutations_rejected(self):
        for key,value in (('profile_id','linux'),('blender_version',[4,3,1]),('blender_version',[4,3,True])):
            with self.subTest(key=key,value=value):self.reject(lambda v:v.update({key:value}),'addon_pin_contract_differs')
    def test_distribution_mutations_rejected(self):
        for key,value in (('filename','other.zip'),('bytes',True),('bytes',405138424),('sha256','f'*64)):
            with self.subTest(key=key):self.reject(lambda v:v['distribution'].update({key:value}),'addon_profile_provenance_differs')
    def test_observation_provenance_mutations_rejected(self):
        for key in self.original['observation']:
            with self.subTest(key=key):self.reject(lambda v:v['observation'].update({key:None}),'addon_profile_provenance_differs')
    def test_hash_domain_labels_cannot_be_swapped(self):
        def swap(v):
            h=v['hash_domains'];h['raw_functions_sha256'],h['loaded_functions_sha256']=h['loaded_functions_sha256'],h['raw_functions_sha256']
        self.reject(swap,'addon_profile_provenance_differs')
    def test_file_inventory_missing_extra_or_invalid_digest_rejected(self):
        self.reject(lambda v:v['files'].pop('data_types.py'),'addon_pin_contract_differs')
        self.reject(lambda v:v['files'].update(extra='a'*64),'addon_pin_contract_differs')
        for digest in ('bad','A'*64,True,None):
            with self.subTest(digest=digest):self.reject(lambda v:v['files'].update({'data_types.py':digest}),'invalid_sha256')
    def test_metadata_inventory_and_fields_exact(self):
        self.reject(lambda v:v['file_metadata'].pop('data_types.py'),'json_fields_differ')
        self.reject(lambda v:v['file_metadata']['data_types.py'].update(extra=1),'json_fields_differ')
    def test_non_crlf_and_non_integer_metadata_rejected(self):
        for key,value in (('bytes',0),('bytes',o.MEMBER_CAP+1),('bytes',True),('crlf_count',0),('crlf_count',-1),('crlf_count',10**9),('bare_lf_count',1),('bare_cr_count',1),('bare_cr_count',False)):
            with self.subTest(key=key,value=value):self.reject(lambda v:v['file_metadata']['data_types.py'].update({key:value}),'addon_profile_newline_metadata_differs')
    def test_each_function_domain_requires_exact_module_and_function_names(self):
        for domain in ('raw_functions_sha256','loaded_functions_sha256'):
            with self.subTest(domain=domain):
                self.reject(lambda v:v[domain].update(extra={}), 'json_fields_differ')
                self.reject(lambda v:v[domain]['import_fbx.py'].pop('blen_read_animations'),'json_fields_differ')
                self.reject(lambda v:v[domain]['import_fbx.py'].update(extra='a'*64),'json_fields_differ')
    def test_each_function_domain_requires_raw_sha256_strings(self):
        for domain in ('raw_functions_sha256','loaded_functions_sha256'):
            with self.subTest(domain=domain):self.reject(lambda v:v[domain]['import_fbx.py'].update(blen_read_animations=True),'invalid_sha256')
    def test_function_domain_swap_changes_pinned_profile_identity(self):
        value=copy.deepcopy(self.original)
        value['raw_functions_sha256'],value['loaded_functions_sha256']=value['loaded_functions_sha256'],value['raw_functions_sha256']
        write_json(self.f.context/'OFFICIAL_ADDON_PINS.json',value)
        with self.assertRaisesRegex(o.ObservationError,'input_pin_mismatch'):self.pins()
    def test_old_materialized_context_path_rejected(self):
        old=self.f.context.parent/'context-v2';shutil.copytree(self.f.context,old)
        self.f.config['roots']['context_package']=str(old);self.f.write_config()
        with self.assertRaisesRegex(o.ObservationError,'context_root_outside_materialized'):self.f.run()
    def test_exact_profile_bytes_required_even_when_semantically_equal(self):
        with (self.f.context/'OFFICIAL_ADDON_PINS.json').open('ab') as stream:stream.write(b' ')
        with self.assertRaisesRegex(o.ObservationError,'input_pin_mismatch'):self.pins()
    def test_context_cannot_substitute_a_different_profile_pin(self):
        manifest=self.f.context/'PINS.json';write_json(manifest,{'OFFICIAL_ADDON_PINS.json':'f'*64})
        self.f.patches['CONTEXT_PINS_SHA']=o.sha(manifest.read_bytes())
        with self.assertRaisesRegex(o.ObservationError,'context_addon_binding_differs'):self.pins()
    def test_raw_equality_never_admits_or_changes_original_failure(self):
        before=(self.f.evidence/'summary.json').read_bytes();result=self.f.run()
        self.assertTrue(all(r['archive_equals_installed'] and r['installed_raw_matches_expected'] and r['archive_raw_matches_expected'] for r in result['files']))
        for key in ('native_admission','animation_proof','normalized_hash_acceptance','native_outcome_modified'):self.assertIs(result[key],False)
        self.assertEqual(before,(self.f.evidence/'summary.json').read_bytes())
    def test_lf_substitution_never_becomes_raw_match(self):
        for name,raw in self.f.expected.items():(self.f.addon/name).write_bytes(raw)
        result=self.f.run()
        self.assertTrue(all(not row['installed_raw_matches_expected'] and row['archive_raw_matches_expected'] and not row['archive_equals_installed'] for row in result['files']))
        self.assertFalse(result['normalized_hash_acceptance']);self.assertFalse(result['native_admission'])
if __name__=='__main__':unittest.main(verbosity=2)
