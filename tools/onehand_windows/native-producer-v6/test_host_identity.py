"""Bounded synthetic source tests; no native process, assets, or Windows API."""
import ast
import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import host_identity as h
import pinned_code
import transport_binding

HERE = Path(__file__).absolute().parent
CONTEXT = HERE.parent/'windows-context-preparation-v3'
if not CONTEXT.is_dir():
    CONTEXT = HERE.parent/'context-v3'
ORCHESTRATION = HERE.parent/'windows-host-orchestration-v9'
if not ORCHESTRATION.is_dir():
    ORCHESTRATION = HERE.parent/'orchestration-v9'
if not ORCHESTRATION.is_dir():
    ORCHESTRATION = HERE.parent/'orchestration'
cc = pinned_code.load_context(CONTEXT)
PROCESS = next(path for path in (HERE.parent/'process-v2', HERE.parent/'published-pr77'/'tools'/'onehand_windows'/'process-v2') if path.is_dir())
ADAPTER = transport_binding.verify_transport(SimpleNamespace(root=lambda _: PROCESS, cc=cc, raw={'dependencies':{'transport_pins_sha256':transport_binding.TRANSPORT_PINS_SHA}}), production=False)
OUTER = {'system': 'Windows', 'release': '2022Server', 'version': '10.0.20348', 'machine': 'AMD64'}
NATIVE = {**OUTER, 'release': '10'}


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cc.canonical(value))
    return pin(path)


class ComparisonTests(unittest.TestCase):
    def test_release_diff_is_allowed_only_cross_role(self):
        self.assertEqual(h.compare_cross_role(OUTER, NATIVE), NATIVE)
        with self.assertRaisesRegex(ValueError, '^native host release differs$'):
            h.compare_native_host(OUTER, NATIVE)

    def test_all_native_fields_match_probe_exactly(self):
        self.assertEqual(h.compare_native_host(NATIVE, dict(NATIVE)), NATIVE)
        for field, value in [('release', '11'), ('version', '10.0.26100'), ('system', 'Linux'), ('machine', 'x86_64')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                h.compare_native_host(NATIVE, {**NATIVE, field: value})

    def test_cross_role_version_mismatch_not_normalized(self):
        with self.assertRaisesRegex(ValueError, '^cross-role host version differs$'):
            h.compare_cross_role(OUTER, {**NATIVE, 'version': '10.0.26100'})

    def test_native_machine_empty_or_alias_rejected(self):
        for machine in ('', 'x86_64', 'amd64', 'ARM64', 'unknown', None, True, ['AMD64']):
            with self.subTest(machine=machine), self.assertRaisesRegex(ValueError, '^native host machine invalid$'):
                h.validate_observed_host({**NATIVE, 'machine': machine})

    def test_missing_or_unknown_fields_rejected(self):
        for data in ({k:v for k,v in NATIVE.items() if k != 'release'}, {**NATIVE, 'token': 'sentinel'}, []):
            with self.assertRaisesRegex(ValueError, '^native host fields malformed$'):
                h.validate_observed_host(data)

    def test_empty_unknown_oversized_and_nonstring_fields_rejected(self):
        for name in h.FIELDS:
            for value in ('', 'unknown', 'x'*129, None, True, {}, 'bad\0value'):
                with self.subTest(field=name, kind=type(value).__name__), self.assertRaises(ValueError):
                    h.validate_observed_host({**NATIVE, name: value})

    def test_version_and_release_malformed_rejected(self):
        for version in ('10.0', '10.0.20348.1', '10.0.synthetic', ' 10.0.20348', '10.0.20348 '):
            with self.assertRaisesRegex(ValueError, '^native host version invalid$'):
                h.validate_observed_host({**NATIVE, 'version': version})
        with self.assertRaisesRegex(ValueError, '^native host release invalid$'):
            h.validate_observed_host({**NATIVE, 'release': 'server release'})

    def native(self, actual=NATIVE, sys_platform='win32', pointer_bytes=8):
        platform = SimpleNamespace(**{k:(lambda v=v:v) for k,v in actual.items()})
        with (mock.patch.object(h, 'sys', SimpleNamespace(platform=sys_platform)),
              mock.patch.object(h, 'struct', SimpleNamespace(calcsize=lambda _: pointer_bytes)),
              mock.patch.object(h, 'platform', platform)):
            return h.require_native_host(NATIVE, OUTER, 'a'*64)

    def test_native_own_tuple_passes_without_outer_release_match(self):
        self.assertEqual(self.native(), NATIVE)

    def test_native_32bit_or_nonwindows_rejected(self):
        for platform, width in [('win32', 4), ('linux', 8)]:
            with self.assertRaisesRegex(ValueError, '^actual 64-bit Windows native Python host required$'):
                self.native(sys_platform=platform, pointer_bytes=width)

    def test_native_observation_change_rejected(self):
        with self.assertRaisesRegex(ValueError, '^native host release differs$'):
            self.native(actual={**NATIVE, 'release': '11'})

    def test_native_entry_no_longer_uses_supervisor_tuple(self):
        tree = ast.parse((HERE/'native_entry.py').read_bytes())
        self.assertNotIn('ctx.host.require_current_host()', ast.unparse(tree))
        self.assertIn('host_build(ctx, native=True, current=True)', ast.unparse(tree))

    def test_outer_launcher_and_stage_binding_remain_exact(self):
        predecessor = json.loads((HERE/'HOST_BINDING_PREDECESSOR.json').read_bytes())
        for name in ('stage_context.py', 'pinned_code.py', 'process_evidence.py', 'native_stages.py'):
            self.assertEqual(pinned_code.file_sha(HERE/name), predecessor['files'][name])
        launcher = (HERE/'launch_stage.py').read_text()
        added = "    require(ctx.cc.digest(environment)==host['controller_environment_sha256'],'host-pinned controller environment differs')\n"
        self.assertEqual(launcher.count(added), 1)
        self.assertEqual(hashlib.sha256(launcher.replace(added, '').encode()).hexdigest(), predecessor['files']['launch_stage.py'])
        self.assertIn('ctx.host.require_current_host()', launcher)
        self.assertIn("c.exact(self.pin('host_binding').sha256,self.host.build_sha256", (HERE/'stage_context.py').read_text())

    def test_launcher_rejects_forged_hash_pair_before_side_effects(self):
        import launch_stage as launch
        environment = {'PROCESSOR_ARCHITECTURE':'AMD64', 'SystemRoot':'C:\\Windows'}
        controller_sha = cc.digest(environment)
        transport_sha = ADAPTER.digest(environment)
        self.assertNotEqual(controller_sha, transport_sha)
        host = {'native_environment_sha256':transport_sha, 'native_environment_keys':sorted(environment),
                'controller_environment_sha256':'e'*64}
        ctx = SimpleNamespace(cc=cc, raw={'dependencies':{'producer_pins_sha256':'a'*64}},
                              validate=mock.Mock(), verify_files=mock.Mock(),
                              host=SimpleNamespace(require_current_host=mock.Mock()), output=Path('unused'))
        with (mock.patch.object(launch, 'verify_package'), mock.patch.object(launch, 'verify_transport', return_value=ADAPTER),
              mock.patch.object(launch, 'host_build', return_value=host), mock.patch.object(launch, 'validate_dependencies'),
              mock.patch.object(launch, 'output_cap', return_value=0),
              mock.patch.object(launch, 'capacity', side_effect=RuntimeError('reached capacity only')) as capacity):
            with self.assertRaisesRegex(ValueError, '^host-pinned controller environment differs$'):
                launch.launch(ctx, environment)
            capacity.assert_not_called()
            host['controller_environment_sha256'] = controller_sha
            with self.assertRaisesRegex(RuntimeError, '^reached capacity only$'):
                launch.launch(ctx, environment)
            capacity.assert_called_once()
            self.assertEqual(ctx.host.require_current_host.call_count, 2)

    def test_native_and_outer_current_checks_are_separate_branches(self):
        source = (HERE/'admission.py').read_text()
        tree = ast.parse(source)
        fun = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'host_build')
        current = next(n for n in fun.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == 'current')
        native = current.body[0]
        self.assertEqual(ast.unparse(native.test), 'native')
        self.assertIn('require_native_host', ast.unparse(ast.Module(body=native.body, type_ignores=[])))
        self.assertNotIn('require_current_host', ast.unparse(ast.Module(body=native.body, type_ignores=[])))
        self.assertIn('ctx.host.require_current_host()', ast.unparse(ast.Module(body=native.orelse, type_ignores=[])))


@dataclasses.dataclass
class SyntheticLimits:
    stdout_mode: str
    max_stdout_bytes: int
    max_stderr_bytes: int


class ProbeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidate = self.root/'private'/'session'/'candidates'/'candidate'
        self.bundle = self.root/'bundle'
        self.bundle.mkdir()
        self.tools = {}
        for name in ('python', 'python_runtime', 'blender', 'blender_python_runtime'):
            path = self.bundle/(name+'.synthetic')
            path.write_bytes(('synthetic-'+name).encode())
            self.tools[name] = pin(path)
        self.source = self.root/'protected'/'probe_blender.py'
        self.source.parent.mkdir()
        self.source.write_bytes((ORCHESTRATION/'probe_blender.py').read_bytes())
        self.probe_path = self.candidate/'blender-observed.json'
        self.context_path = self.candidate/'contexts'/'blender-host-observation-command.json'
        self.terminal = self.candidate/'process'/'blender-host-observation'/'terminal.json'
        self.terminal.parent.mkdir(parents=True)
        self.terminal.write_bytes(b'{"synthetic":true}')
        self.ctx = SimpleNamespace(cc=cc, candidate_root=self.candidate,
            owner_lock=self.root/'private'/'session'/'native-owner.lock',
            host=cc.HostBuildBinding.parse({'runner_id':'runner', 'run_id':'run', **OUTER, 'build_sha256':'a'*64}),
            root=lambda _: self.bundle)
        self.probe = {'schema': h.PROBE_SCHEMA, 'blender_version':[4,3,2], 'blender_build_hash':'synthetic-build',
            'blender_binary': self.tools['blender']['path'], 'blender_binary_sha256':self.tools['blender']['sha256'],
            'python_runtime':self.tools['blender_python_runtime']['path'], 'python_runtime_sha256':self.tools['blender_python_runtime']['sha256'],
            'fbx_addon_file':str(self.bundle/'addons'/'io_scene_fbx'/'__init__.py'), 'background':True,
            'autoexec_disabled':True, 'source_saved':False, 'rendered':False, 'sys_platform':'win32',
            'pointer_bits':64, 'observed_host':dict(NATIVE)}
        self.command = h.probe_command(self.tools['blender']['path'], self.source, self.probe_path)
        self.environment = {'PROCESSOR_ARCHITECTURE':'AMD64', 'SystemRoot':'C:\\Windows'}
        self.controller_environment_sha = cc.digest(self.environment)
        self.transport_environment_sha = ADAPTER.digest(self.environment)
        self.assertNotEqual(self.controller_environment_sha, self.transport_environment_sha)
        self.context = {'schema':'rust-duty-onehand-controller-command/v1', 'label':'blender-host-observation',
            'argv':self.command, 'cwd':str(self.candidate), 'executable':{**self.tools['blender'], 'bytes':Path(self.tools['blender']['path']).stat().st_size},
            'environment_sha256':self.controller_environment_sha, 'host':{'runner_id':'runner', 'run_id':'run', **OUTER, 'build_sha256':'b'*64}}
        self.host = {'native_observed_host':dict(NATIVE), 'tools':self.tools, 'blender_build_hash':'synthetic-build',
            'addon_relative':'addons/io_scene_fbx', 'native_environment_sha256':self.transport_environment_sha,
            'controller_environment_sha256':self.controller_environment_sha,
            'native_environment_keys':['PROCESSOR_ARCHITECTURE','SystemRoot'],
            'native_observation':{'probe':write(self.probe_path,self.probe), 'command_context':write(self.context_path,self.context),
                                  'process_terminal':pin(self.terminal), 'probe_source':pin(self.source)}}
        self.seen = []

    def tearDown(self):
        self.temp.cleanup()

    def validate(self, validator=None):
        def capture(adapter, root, expected):
            self.seen.append((root, expected))
            return {'completed':True}
        return h.verify_probe_binding(self.ctx, self.host, SimpleNamespace(Limits=SyntheticLimits), validator or capture)

    def repin_probe(self):
        self.host['native_observation']['probe'] = write(self.probe_path, self.probe)

    def repin_context(self):
        self.host['native_observation']['command_context'] = write(self.context_path, self.context)

    def test_full_completed_process_validator_receives_exact_bindings(self):
        self.validate()
        root, expected = self.seen[0]
        self.assertEqual(root, self.terminal.parent)
        self.assertEqual(expected['command'], self.command)
        self.assertEqual(expected['host_binding']['observed_host'], OUTER)
        self.assertEqual(expected['host_binding']['build_sha256'], 'b'*64)
        self.assertEqual(expected['host_binding']['context_sha256'], cc.digest(self.context))
        self.assertEqual(expected['host_binding']['environment_sha256'], self.transport_environment_sha)
        self.assertEqual(self.context['environment_sha256'], self.host['controller_environment_sha256'])
        self.assertEqual(expected['host_binding']['environment_keys'], self.host['native_environment_keys'])
        self.assertEqual(expected['host_binding']['owner_lock'], str(self.ctx.owner_lock))
        self.assertEqual(expected['supervisor_python']['sha256'], self.tools['python']['sha256'])
        self.assertEqual(expected['limits']['max_stdout_bytes'], 4*1024**2)
        self.assertEqual(expected['limits']['max_stderr_bytes'], 1024**2)

    def test_missing_or_unknown_provenance_reference_rejected(self):
        del self.host['native_observation']['process_terminal']
        with self.assertRaises(ValueError): self.validate()

    def test_mutated_unrepinned_probe_rejected(self):
        self.probe_path.write_bytes(self.probe_path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'pinned bytes differ'): self.validate()

    def test_mutated_unrepinned_terminal_rejected(self):
        self.terminal.write_bytes(b'{"tampered":true}')
        with self.assertRaisesRegex(ValueError, 'pinned bytes differ'): self.validate()

    def test_resealed_wrong_native_observation_rejected(self):
        self.probe['observed_host']['release'] = '11'; self.repin_probe()
        with self.assertRaisesRegex(ValueError, '^native host release differs$'): self.validate()

    def test_manifest_cross_role_version_rejected(self):
        self.host['native_observed_host']['version'] = '10.0.26100'
        with self.assertRaisesRegex(ValueError, '^cross-role host version differs$'): self.validate()

    def test_resealed_wrong_probe_runtime_and_executable_rejected(self):
        for key in ('python_runtime_sha256', 'blender_binary_sha256'):
            original = self.probe[key]; self.probe[key] = 'e'*64; self.repin_probe()
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()
            self.probe[key] = original; self.repin_probe()

    def test_resealed_wrong_probe_mode_width_version_or_unknown_rejected(self):
        original = copy.deepcopy(self.probe)
        for key,value in [('sys_platform','linux'),('pointer_bits',32),('pointer_bits',True),('source_saved',True),
                          ('rendered',True),('blender_version',[4,4,0]),('unreviewed','sentinel')]:
            self.probe = {**original,key:value}; self.repin_probe()
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()

    def test_resealed_wrong_context_run_command_or_environment_rejected(self):
        original = copy.deepcopy(self.context)
        mutations = [lambda v:v['host'].update(run_id='other-run'),
                     lambda v:v['host'].update(runner_id='other-runner'),
                     lambda v:v['host'].update(release='10'),
                     lambda v:v.update(argv=['unreviewed']),
                     lambda v:v.update(environment_sha256='bad'),
                     lambda v:v.update(environment_sha256='e'*64),
                     lambda v:v.update(cwd=str(self.root))]
        for mutation in mutations:
            self.context = copy.deepcopy(original); mutation(self.context); self.repin_context()
            with self.assertRaises(ValueError): self.validate()

    def test_same_named_foreign_terminal_rejected(self):
        foreign = self.root/'foreign'/'terminal.json'; foreign.parent.mkdir(); foreign.write_bytes(self.terminal.read_bytes())
        self.host['native_observation']['process_terminal'] = pin(foreign)
        with self.assertRaises(ValueError): self.validate()

    def test_changed_probe_source_even_if_resealed_rejected(self):
        self.source.write_bytes(self.source.read_bytes()+b'\n')
        self.host['native_observation']['probe_source'] = pin(self.source)
        with self.assertRaisesRegex(ValueError, 'native observation probe source'): self.validate()

    def test_process_validator_failure_not_swallowed(self):
        def failed(*args): raise ValueError('synthetic incomplete probe process')
        with self.assertRaisesRegex(ValueError, 'synthetic incomplete probe process'): self.validate(failed)

    def test_mutation_during_process_validation_rejected(self):
        def mutate(*args): self.probe_path.write_bytes(b'changed during validation')
        with self.assertRaisesRegex(ValueError, 'pinned bytes differ'): self.validate(mutate)


if __name__ == '__main__':
    unittest.main(verbosity=2)
