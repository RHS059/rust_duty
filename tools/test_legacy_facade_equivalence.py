"""Synthetic archive/pixel/process controls; no historical or Windows execution."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
import run_legacy_facade_equivalence as runner


def capture(folder, role, pose):
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/f'{pose}.png'
    for suffix,color in (('',runner.authored.BACKGROUND),('.world.png',runner.authored.WORLD_BACKGROUND)):
        image = Image.new('RGBA',runner.EXTENT,color)
        ImageDraw.Draw(image).rectangle((400,300,700,539),fill=(100,100,100,255))
        image.save(str(path)+suffix)
    metadata = {'capture':'native offscreen viewmodel','width':960,'height':540,
                'hfov':76,'ads':int(pose=='ads'),'reload_phase':None}
    if role == 'current':metadata.update(requested='gl',backend='OpenGl',adapter='llvmpipe (test)')
    Path(str(path)+'.json').write_text(json.dumps(metadata))
    light = {'schema':'rust-duty-lighting-capture/v1','yaw_degrees':-90,'pitch_degrees':0,
             'world_light':[0,1,0],'view_light':[0,1,0],'ambient':.35,'diffuse':.65,'simulation_time':0}
    Path(str(path)+'.lighting.json').write_text(json.dumps(light))
    if role == 'current':
        Path(str(path)+'.world.png.json').write_text(json.dumps({
            'capture':'native window','width':960,'height':540,'requested':'gl','backend':'OpenGl','adapter':'llvmpipe (test)'}))
    return path


class LegacyEquivalenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root = Path(temp.name)
        self.count = 0

    def archive(self, identity_change=None, extra=(), exe=b'MZtest game', identity_text=None):
        self.count += 1;path = self.root/f'reference-{self.count}.zip'
        identity = copy.deepcopy(runner.REFERENCE_IDENTITY)
        identity['executable'] = {'name':'vector-range.exe','size':len(exe),'sha256':hashlib.sha256(exe).hexdigest()}
        if identity_change:identity_change(identity)
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('vector-range.exe',exe)
            z.writestr('BUILD_IDENTITY.json',identity_text if identity_text is not None else json.dumps(identity))
            for name,data in extra:
                if isinstance(name,str):
                    member = zipfile.ZipInfo(name)
                    # ZipInfo normalizes backslashes on Windows. Preserve the
                    # malicious on-disk name so the real reader sees the input.
                    member.filename = name
                else:member = name
                z.writestr(member,data)
        return path

    def pin(self,path):
        # Production exposes no arbitrary reference-run/hash override.
        return patch.dict(runner.REFERENCE,{'zip_bytes':path.stat().st_size,'zip_sha256':runner.authored.sha256(path)})

    def extract(self,path):
        with self.pin(path):return runner.reference_executable(path,self.root/f'out-{self.count}')

    def test_extracts_only_exact_executable_and_identity(self):
        path = self.archive(extra=[('assets/private-unrelated.bin',b'never extract'),('launch.ps1',b'never execute')])
        result = self.extract(path)
        self.assertEqual(set(p.name for p in (self.root/'out-1').iterdir()),{'vector-range.exe','BUILD_IDENTITY.json'})
        self.assertEqual(result['identity']['source']['commit'],runner.REFERENCE_IDENTITY['source']['commit'])
        self.assertTrue(result['selected_member_crcs_checked'])
        self.assertFalse(result['all_member_crcs_checked'])

    def test_fixed_archive_digest_and_size_are_required(self):
        path = self.archive()
        with self.assertRaisesRegex(ValueError,'ZIP size'):runner.reference_executable(path,self.root/'out')
        with patch.dict(runner.REFERENCE,{'zip_bytes':path.stat().st_size}):
            with self.assertRaisesRegex(ValueError,'ZIP digest'):runner.reference_executable(path,self.root/'out')

    def test_wrong_historical_source_run_or_numeric_type_fails(self):
        for change in (lambda d:d['source'].update(commit='a'*40),
                       lambda d:d['source'].update(run_id=123),
                       lambda d:d['source'].update(run_attempt=True),
                       lambda d:d.update(sequence=True),
                       lambda d:d.update(target='other')):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):self.extract(self.archive(change))

    def test_duplicate_identity_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON'):
            self.extract(self.archive(identity_text='{"source":{},"source":{}}'))

    def test_unsafe_windows_names_and_case_collisions_fail(self):
        for name in ('../outside','C:/outside','a\\b','CON.txt','a./b','vector-RANGE.exe'):
            with self.subTest(name=name):
                path = self.archive(extra=[(name,b'x')])
                with zipfile.ZipFile(path) as archive:
                    self.assertIn(name,[info.orig_filename for info in archive.infolist()])
                with self.assertRaises(ValueError):self.extract(path)

    def test_raw_backslash_fixture_survives_windows_zip_normalization(self):
        with patch.object(zipfile.os,'sep','\\'):
            path = self.archive(extra=[('a\\b',b'x')])
            with zipfile.ZipFile(path) as archive:
                member = archive.infolist()[-1]
                self.assertEqual(member.orig_filename,'a\\b')
                self.assertEqual(member.filename,'a/b')
            with self.assertRaisesRegex(ValueError,'backslash path'):self.extract(path)

    def test_zip_links_and_file_directory_conflicts_fail(self):
        link = zipfile.ZipInfo('link');link.create_system = 3;link.external_attr = (stat.S_IFLNK|0o777)<<16
        reparse = zipfile.ZipInfo('junction');reparse.external_attr = 0x400
        for extra in ([(link,b'target')],[(reparse,b'target')],[('a',b'x'),('a/b',b'x')]):
            with self.assertRaises(ValueError):self.extract(self.archive(extra=extra))

    def test_missing_root_member_and_executable_mismatch_fail(self):
        path = self.root/'nested.zip'
        with zipfile.ZipFile(path,'w') as z:z.writestr('nested/vector-range.exe',b'MZ')
        with self.pin(path),self.assertRaisesRegex(ValueError,'missing root'):
            runner.reference_executable(path,self.root/'nested-out')
        with self.assertRaisesRegex(ValueError,'digest/size'):
            self.extract(self.archive(lambda d:d['executable'].update(sha256='0'*64)))
        with self.assertRaisesRegex(ValueError,'Windows EXE'):
            self.extract(self.archive(exe=b'not a Windows executable'))

    def test_selected_member_bound_and_existing_destination_fail(self):
        path = self.archive()
        with patch.object(runner,'MAX_EXE',1),self.assertRaisesRegex(ValueError,'exceeds bounds'):self.extract(path)
        out = self.root/'existing';out.mkdir();(out/'sentinel').write_text('keep')
        with self.pin(path),self.assertRaisesRegex(ValueError,'fresh'):runner.reference_executable(path,out)
        self.assertEqual((out/'sentinel').read_text(),'keep')

    def test_commands_use_existing_static_mode_and_skip_only_dedicated_witness(self):
        for role in ('reference','current'):
            for pose in ('hip','ads'):
                argv = runner.command('game.exe','weapon.vrm','settings.cfg','capture.png',role,pose)
                self.assertEqual('--renderer=gl' in argv,role=='current')
                self.assertEqual('--capture-ads' in argv,pose=='ads')
                for flag in ('--no-update','--reference-viewport','--profile=kestrel','--capture','--capture-lighting'):
                    self.assertIn(flag,argv)
                self.assertFalse(any(s.startswith(('--capture-frame-witness','--animation-manifest','--viewmodel-','--arms-asset')) for s in argv))

    def pair(self,pose='hip'):
        return capture(self.root/'reference','reference',pose),capture(self.root/'current','current',pose)

    def test_identical_rgba_and_common_json_pass(self):
        a,b = self.pair()
        result = runner.compare_pose(a.parent,b.parent,'hip')
        self.assertTrue(result['exact_bounded_match'])
        self.assertTrue(result['shared_json_equal'])
        self.assertTrue(all(v['changed_pixels']==0 for v in result['images'].values()))

    def test_single_channel_difference_is_retained_without_tolerance(self):
        a,b = self.pair()
        with Image.open(b) as image:
            image.putpixel((500,350),(100,99,100,255));image.save(b)
        result = runner.compare_pose(a.parent,b.parent,'hip');pixels = result['images']['viewmodel']
        self.assertFalse(result['exact_bounded_match']);self.assertEqual(pixels['changed_pixels'],1)
        self.assertEqual(pixels['maximum_absolute_channel_difference'],[0,1,0,0])
        self.assertEqual(pixels['changed_bounds_inclusive'],[500,350,500,350])
        self.assertFalse(pixels['tolerance_applied'])

    def test_json_type_and_exact_decimal_differences_are_not_hidden(self):
        a,b = self.pair()
        metadata = json.loads(Path(str(b)+'.json').read_text());metadata['hfov'] = 76.0
        Path(str(b)+'.json').write_text(json.dumps(metadata))
        light = json.loads(Path(str(b)+'.lighting.json').read_text());light['ambient'] = .3500000001
        Path(str(b)+'.lighting.json').write_text(json.dumps(light))
        result = runner.compare_pose(a.parent,b.parent,'hip')
        self.assertFalse(result['shared_json_equal']);self.assertEqual(len(result['json_differences']),2)
        self.assertEqual(result['numeric_representation_only_fields'],['hfov'])
        self.assertTrue(result['images']['viewmodel']['exact_rgba_equal'])

    def test_png_header_extent_is_checked_before_decode(self):
        path = self.root/'oversized.png';Image.new('RGBA',(1920,1080),(0,0,0,255)).save(path)
        with patch('PIL.PngImagePlugin.PngImageFile.load',side_effect=AssertionError('decoded too early')):
            with self.assertRaisesRegex(ValueError,'960x540'):runner.pixels(path,runner.authored.BACKGROUND)

    def test_nonopaque_or_truncated_png_fails(self):
        a,_ = self.pair()
        with Image.open(a) as image:image.putpixel((400,300),(100,100,100,254));image.save(a)
        with self.assertRaisesRegex(ValueError,'opaque'):runner.pixels(a,runner.authored.BACKGROUND)
        capture(a.parent,'reference','hip');a.write_bytes(a.read_bytes()[:-4])
        with self.assertRaises(ValueError):runner.pixels(a,runner.authored.BACKGROUND)

    def mock_run(self, *, difference=False, failed_pose=None, mutate_input=False, stale_identity=False):
        root = self.root/'repo';root.mkdir();(root/'assets/weapons').mkdir(parents=True)
        asset = root/'assets/weapons/hk416a5.vrm';asset.write_bytes(b'approved synthetic fixture')
        executable = root/'game.exe';executable.write_bytes(b'MZcurrent synthetic fixture')
        runtime = self.root/'mesa';runtime.mkdir();archive = self.archive()
        evidence = self.root/'evidence'
        current_identity = {'version':'0.1.11','build_number':'100.1','display_version':'0.1.11+build.100.1',
                            'source':{'commit':'a'*40}}
        def stage(exe,rt,lock,destination):
            destination.mkdir();(destination/'vector-range.exe').write_bytes(exe.read_bytes());return {'loaded_modules_verified':False}
        def execute(argv,cwd,logs,timeout):
            self.assertEqual(os.environ['GALLIUM_DRIVER'],'llvmpipe')
            self.assertEqual(Path(argv[0]).parent,cwd)
            role = 'reference' if Path(argv[0]).name.startswith('reference-') else 'current'
            if argv[1].startswith('--build-'):
                key = {'--build-version':'version','--build-number':'build_number','--build-label':'display_version'}[argv[1]]
                expected = runner.REFERENCE_IDENTITY if role=='reference' else current_identity
                logs.mkdir(parents=True)
                (logs/'invocation.json').write_text(json.dumps({'command':argv,'cwd':str(cwd),'timeout_seconds':timeout}))
                (logs/'process.json').write_text(json.dumps({'schema':'rust-duty-capture-process/v1','status':'passed',
                    'exit_code':0,'pid':123,'png_files':0,'timeout_seconds':timeout,'elapsed_seconds':1}))
                (logs/'stdout.log').write_text('stale' if stale_identity and role=='current' else expected[key]+'\n')
                (logs/'stderr.log').write_text('')
                return
            pose = 'ads' if '--capture-ads' in argv else 'hip'
            output = Path(next(s.split('=',1)[1] for s in argv if s.startswith('--output=')))
            path = capture(output.parent,role,pose)
            if difference and role == 'current':
                with Image.open(path) as image:image.putpixel((500,350),(99,100,100,255));image.save(path)
            logs.mkdir(parents=True)
            bad = (role,pose) == failed_pose
            (logs/'invocation.json').write_text(json.dumps({'command':argv,'cwd':str(cwd),'timeout_seconds':timeout}))
            (logs/'process.json').write_text(json.dumps({'schema':'rust-duty-capture-process/v1','status':'failed' if bad else 'passed',
                'exit_code':1 if bad else 0,'pid':123,'png_files':1,'timeout_seconds':timeout,'elapsed_seconds':1}))
            (logs/'stdout.log').write_text('')
            (logs/'stderr.log').write_text('Loaded VRMESH01 weapon: 30 mesh parts\n'+
                ('renderer requested=gl backend=OpenGl adapter=llvmpipe (test)\n' if role == 'current' else ''))
            if mutate_input:executable.write_bytes(b'MZchanged input')
        env = {'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'100','GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'RHS059/rust_duty'}
        with self.pin(archive),patch.object(runner.sys,'platform','win32'),patch.dict(os.environ,env), \
             patch.object(runner.subprocess,'check_output',return_value='a'*40),patch.object(runner.subprocess,'run'), \
             patch.object(runner.build_identity,'context',return_value=current_identity), \
             patch.object(runner.calibrated,'ASSET_SHA256',runner.authored.sha256(asset)), \
             patch.object(runner.vrpack,'inspect_vrm',return_value={'crc32':'fc786964','meshes':30,'textures':0,'texture_bytes':0}), \
             patch.object(runner,'stage_runtime',side_effect=stage),patch.object(runner,'validate_runtime'), \
             patch.object(runner.authored,'execute',side_effect=execute):
            return runner.run(archive,executable,root,runtime,evidence)

    def test_mock_native_wrapper_requires_all_four_and_preserves_identity_limits(self):
        result = self.mock_run()
        self.assertTrue(result['passed']);self.assertEqual(len(result['captures']),4)
        self.assertTrue((self.root/'evidence/summary.json').is_file())
        self.assertTrue(all(r['adapter'] is None for r in result['captures'] if r['role']=='reference'))
        self.assertFalse(result['loaded_modules_verified'])

    def test_mock_pixel_difference_retains_both_poses_and_nonpass(self):
        result = self.mock_run(difference=True)
        self.assertEqual(result['status'],'differences-observed');self.assertFalse(result['passed'])
        self.assertTrue(result['comparison_complete']);self.assertEqual(len(result['captures']),4)

    def test_mock_process_failure_never_passes_and_other_captures_continue(self):
        result = self.mock_run(failed_pose=('reference','hip'))
        self.assertFalse(result['passed']);self.assertEqual(result['status'],'failed')
        self.assertEqual(len(result['captures']),3);self.assertEqual(len(result['comparisons']),1)

    def test_mock_input_mutation_fails(self):
        result = self.mock_run(mutate_input=True)
        self.assertFalse(result['passed'])
        self.assertIn('current EXE changed',result['checks'][-1]['error'])

    def test_mock_stale_current_build_identity_fails_before_capture(self):
        result = self.mock_run(stale_identity=True)
        self.assertFalse(result['passed']);self.assertEqual(result['captures'],[])
        self.assertIn('embedded version differs',result['checks'][-1]['error'])

    def test_nonwindows_fails_before_extraction_or_execution(self):
        with patch.object(runner.sys,'platform','linux'),patch.object(runner,'reference_executable') as extract, \
             patch.object(runner.authored,'execute') as execute:
            with self.assertRaisesRegex(ValueError,'native Windows'):runner.run('old.zip','game.exe',self.root,self.root,self.root/'evidence')
            extract.assert_not_called();execute.assert_not_called()


if __name__ == '__main__':unittest.main()
