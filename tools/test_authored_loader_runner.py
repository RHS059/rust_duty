"""Native-gate orchestration with nonexecutable process/asset fixtures only."""
import contextlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import performance_matrix as matrix
import run_authored_loader_pair as loader
import run_cpu_image_preservation as pair
import test_authored_loader_pair as fixtures


class LoaderNativeFlowTests(unittest.TestCase):
    def flow(self, mutation=None):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        base=Path(temporary.name).resolve();root=base/'checkout';output=base/'evidence'
        root.mkdir();output.mkdir();matrix.write_json(output/'materialize.json',{'synthetic':True})
        old={name:('old '+name).encode() for name in pair.LOADER_BASELINE}
        production={'Cargo.toml':b'synthetic source',pair.ARENA_PATH:b'current arena',
                    pair.UPLOAD_POLICY_PATH:b'pub const REUSE_ENABLED: bool = true;\n',
                    **{name:('new '+name).encode() for name in old}}
        harness={name:('common fixture '+name).encode() for name in loader.HARNESS_PATHS}
        for name,raw in {**production,**harness,'assets/animations.cfg':b'original manifest',
                         'assets/locomotion/asset.vrs':b'nonexecutable synthetic asset'}.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        if mutation=='private_assets':(root/'assets/weapons').mkdir()
        if mutation=='stale_output':(output/'summary.json').write_bytes(b'previous evidence')
        events=[];changed_compiler=[];self.last=(root,output,events)
        compiler={'rustc':'release: 1.99.0\nhost: x86_64-pc-windows-msvc\n','cargo':'cargo 1.99.0 synthetic'}
        device={'backend':'Dx12','adapter':'Microsoft Basic Render Driver','synthetic':True}
        def source(_):
            return {'commit':'a'*40,'tree':'b'*40,'files_sha256':loader.profile.inventory(root)}
        def config(cwd,env):
            if (Path(cwd)/'.cargo/config.toml').exists():raise ValueError('unbound Cargo configuration')
        def logged(command,cwd,directory,env,timeout,executable_sha256=None):
            directory.mkdir();(directory/'stdout.log').write_bytes(b'synthetic stdout');(directory/'stderr.log').write_bytes(b'synthetic stderr')
            matrix.write_json(directory/'invocation.json',{'command':list(map(str,command)),'timeout':timeout})
            if command[0]=='cargo':
                label=Path(cwd).name.removesuffix('-source');events.append(('build',label))
                self.assertEqual([command[i+1] for i,x in enumerate(command) if x=='--example'],list(loader.EXAMPLES))
                target=Path(env['CARGO_TARGET_DIR'])/'debug/examples';target.mkdir(parents=True)
                for name in loader.EXAMPLES:(target/(name+'.exe')).write_bytes(('synthetic '+label+' '+name).encode())
                if mutation=='build_timeout':raise subprocess.TimeoutExpired(command,timeout)
                if label=='candidate':
                    paths={'source':Path(cwd)/'src/weapon_model.rs',
                           'receipt':output/'sources/baseline-source.json',
                           'verifier':output/'sources/verifier-source.json',
                           'asset':root/'assets/animations.cfg',
                           'earlier_build_log':output/'baseline-build/stdout.log',
                           'earlier_exe':output/'baseline-target/debug/examples/authored_loader_contract.exe',
                           'build_receipt':output/'baseline-build.json',
                           'materialize':output/'materialize.json'}
                    if mutation in paths:
                        p=paths[mutation];p.write_bytes(p.read_bytes()+b'changed')
                    if mutation=='compiler':changed_compiler.append(True)
                    if mutation=='config':
                        p=Path(cwd)/'.cargo/config.toml';p.parent.mkdir();p.write_bytes(b'not read')
                return
            binary=Path(command[0]);self.assertEqual(matrix.sha256(binary),executable_sha256)
            label='baseline' if 'baseline-target' in str(binary) else 'candidate';name=binary.stem
            out=Path(command[command.index('--output-dir')+1]);events.append(('process',label,name,out.name))
            if name==loader.EXAMPLE:
                self.assertEqual(Path(command[command.index('--manifest')+1]),root/'assets/animations.cfg')
                native='--camera' in command
                if native:self.assertEqual(Path(command[command.index('--camera')+1]),output/'camera-prepare/camera.json')
                receipt=matrix.sha256(output/'sources'/(label+'-source.json'))
                report=fixtures.report_fixture(native,3 if label=='candidate' else 6)
                report['source_receipt_sha256']=receipt
                fixtures.write_outputs(out,report)
                if label=='candidate':
                    paths={'camera':output/'camera-prepare/camera.json',
                           'earlier_corner':output/'baseline-authored/ready-0.corners.bin',
                           'earlier_image':output/'baseline-authored/ready-0.png',
                           'earlier_process':output/'baseline-authored-process/stdout.log',
                           'native_exe':binary}
                    if mutation in paths:
                        p=paths[mutation];p.write_bytes(p.read_bytes()+b'changed')
                    if mutation=='current_corner':(out/'ready-0.corners.bin').write_bytes(b'changed')
                    if mutation=='current_report':
                        report['cases'][0]['commands'][0]['expanded_sha256']='e'*64
                        (out/'report.json').write_bytes(json.dumps(report).encode())
                return
            out.mkdir();(out/'control.png').write_bytes(b'synthetic control')
            if name=='renderer_contract':
                self.assertIn('--renderer=dx12',command);self.assertIn('--force-fallback-adapter',command)
                (out/'capture-is-directory.png').mkdir()
            else:matrix.write_json(out/'report.json',{'synthetic':True})
        patches=[patch.object(loader.sys,'platform','win32'),patch.object(loader,'__file__',str(root/'tools/run_authored_loader_pair.py')),
                 patch.object(loader,'EXTENT',[128,8]),patch.object(pair,'check_environment'),
                 patch.object(pair,'check_cargo_configuration',side_effect=config),patch.object(pair,'git',return_value=b''),
                 patch.object(pair,'toolchain_at',side_effect=lambda _:dict(compiler,changed=True) if changed_compiler else compiler.copy()),
                 patch.object(loader.profile,'checked_source',side_effect=source),
                 patch.object(pair,'PRODUCTION_MANIFEST',matrix.canonical_hash(pair.hashes(production))),
                 patch.object(pair,'LOADER_BASELINE',pair.hashes(old)),
                 patch.object(pair,'read_sources',side_effect=lambda _,commit,paths:
                              old.copy() if commit==pair.LOADER_BASELINE_COMMIT else
                              harness.copy() if paths==loader.HARNESS_PATHS else production.copy()),
                 patch.object(pair,'logged',side_effect=logged),
                 patch.object(loader.process,'validate_renderer_log'),
                 patch.object(loader.controls,'device_evidence',return_value=device),
                 patch.object(loader.controls,'require_same_devices',side_effect=lambda values:device if all(v==device for v in values) else None),
                 patch.object(loader.renderer,'validate_outputs',return_value={'passed':True,'captures':21}),
                 patch.object(loader.controls,'validate_report'),patch.object(loader.controls,'contract_pixels',return_value={'synthetic':21}),
                 patch.object(loader.controls,'exact_pixels',return_value={'synthetic':4}),
                 patch.object(subprocess,'Popen',side_effect=AssertionError('real process forbidden'))]
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            return loader.run(root,output)

    def test_fixture_preserves_expected_manifest_notice_instead_of_rejecting_it(self):
        source=(Path(loader.__file__).resolve().parents[1]/'examples/authored_loader_contract.rs').read_text()
        self.assertNotIn('model.warning().is_none()',source)
        self.assertIn('"warning":model.warning()',source)
        self.assertIn('"manifest route failed to load"',source)
        self.assertIn('"manifest/controller draw failed"',source)

    def test_two_fresh_builds_common_camera_real_reader_and_original_controls(self):
        result=self.flow();root,output,events=self.last
        self.assertTrue(result['passed']);self.assertEqual(result['semantic']['cases'],22)
        self.assertEqual(result['semantic']['reduced_vertices'],66)
        self.assertEqual(result['pixels']['exact_rgba_pairs'],22)
        self.assertEqual(events[:2],[('build','baseline'),('build','candidate')])
        self.assertEqual(len(events),9)
        self.assertEqual(events[2],('process','baseline','authored_loader_contract','camera-prepare'))
        self.assertTrue((output/'control-outputs.zip').is_file())
        self.assertIn('baseline-renderer_contract/capture-is-directory.png',result['control_outputs_archive']['directories'])
        self.assertIsNone(result['performance_improvement'])

    def test_input_and_prior_build_mutations_fail_before_any_capture(self):
        for mutation in ('source','receipt','verifier','asset','earlier_build_log','earlier_exe','build_receipt',
                         'materialize','compiler','config','private_assets','stale_output'):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.flow(mutation)
            self.assertFalse(any(event[0]=='process' for event in self.last[2]))

    def test_later_process_cannot_mutate_any_accepted_command_image_receipt_or_binary(self):
        for mutation in ('camera','earlier_corner','earlier_image','earlier_process','native_exe','current_corner','current_report'):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.flow(mutation)
            self.assertFalse((self.last[1]/'summary.json').exists())
            self.assertTrue((self.last[1]/'failure.json').is_file())

    def test_build_timeout_is_failed_evidence_and_launches_no_capture(self):
        with self.assertRaises(subprocess.TimeoutExpired):self.flow('build_timeout')
        self.assertEqual(self.last[2],[('build','baseline')])
        self.assertEqual(matrix.json_read(self.last[1]/'failure.json')['type'],'TimeoutExpired')


if __name__=='__main__':unittest.main()
