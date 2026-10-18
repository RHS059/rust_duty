"""Role-specific Windows observations, never a host-attestation mechanism.

The supervisor tuple stays unchanged. Embedded Blender is compared to its own
earlier byte-pinned owned probe; system/version/machine must also match the
supervisor exactly. Only the interpreter's release label is role-specific.
No normalization, aliases, inferred environment values or native launches.
"""
import dataclasses
from pathlib import Path
import platform
import re
import struct
import sys

FIELDS = ('system', 'release', 'version', 'machine')
PROBE_SOURCE_SHA = 'cef34876a036fec04d520e835d95f8a3fea7a51cad23bb9140efdae13694a350'
PROBE_SCHEMA = 'rust-duty-official-blender-host-observation/v2'
HOST_SCHEMA = 'rust-duty-windows-native-host/v3'
MIB = 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return type(value) is str and 0 < len(value) <= 128 and '\0' not in value and value.casefold() != 'unknown'


def validate_observed_host(value):
    require(type(value) is dict and set(value) == set(FIELDS), 'native host fields malformed')
    require(_text(value['system']) and value['system'] == 'Windows', 'native host system invalid')
    require(_text(value['release']) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value['release']) is not None,
            'native host release invalid')
    require(_text(value['version']) and re.fullmatch(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,10}', value['version']) is not None,
            'native host version invalid')
    require(_text(value['machine']) and value['machine'] == 'AMD64', 'native host machine invalid')
    return value


def compare_cross_role(expected, actual, context_sha256=None):
    # context_sha256 is intentionally never rendered. The enclosing immutable
    # manifest/process receipts establish context, not this pure comparison.
    validate_observed_host(expected)
    validate_observed_host(actual)
    require(actual['system'] == expected['system'], 'cross-role host system differs')
    require(actual['version'] == expected['version'], 'cross-role host version differs')
    require(actual['machine'] == expected['machine'], 'cross-role host machine differs')
    return actual


def compare_native_host(expected, actual):
    validate_observed_host(expected)
    validate_observed_host(actual)
    require(actual['system'] == expected['system'], 'native host system differs')
    require(actual['release'] == expected['release'], 'native host release differs')
    require(actual['version'] == expected['version'], 'native host version differs')
    require(actual['machine'] == expected['machine'], 'native host machine differs')
    return actual


def require_native_host(expected, outer, context_sha256=None):
    require(sys.platform == 'win32' and struct.calcsize('P') == 8,
            'actual 64-bit Windows native Python host required')
    actual = {'system': platform.system(), 'release': platform.release(),
              'version': platform.version(), 'machine': platform.machine()}
    compare_cross_role(outer, expected, context_sha256)
    compare_native_host(expected, actual)
    compare_cross_role(outer, actual, context_sha256)
    return actual


def probe_command(executable, source, output):
    return [str(executable), '--background', '--factory-startup', '--disable-autoexec',
            '--threads', '1', '--python-exit-code', '1', '--python', str(source), '--', str(output)]


def verify_probe_binding(ctx, host, adapter, process_validator):
    """Reconsume retained probe bytes and their exact completed owned process.

    The probe runs before host-binding.json exists, so its initial build digest
    is retained in the pinned command context. Its run IDs, OS tuple, command,
    executable, runtime, owner lock and environment all remain exact.
    """
    c = ctx.cc
    compare_cross_role(ctx.host.expected_host, host['native_observed_host'])
    refs = host['native_observation']
    c.exact_keys(refs, ('probe', 'command_context', 'process_terminal', 'probe_source'), 'native observation')
    pins = {name: c.FilePin.parse(name, value) for name, value in refs.items()}
    expected_paths = {'probe': ctx.candidate_root/'blender-observed.json',
                      'command_context': ctx.candidate_root/'contexts'/'blender-host-observation-command.json',
                      'process_terminal': ctx.candidate_root/'process'/'blender-host-observation'/'terminal.json'}
    for name, expected in expected_paths.items():
        c.exact(pins[name].path, expected, 'owned native observation path')
    c.exact(pins['probe_source'].sha256, PROBE_SOURCE_SHA, 'native observation probe source')
    require(not pins['probe_source'].path.is_relative_to(ctx.candidate_root), 'native probe source must be protected')
    for pin in pins.values():
        pin.verify()
    probe = c.strict_json(pins['probe'].path, cap=16*1024)
    c.exact_keys(probe, ('schema', 'blender_version', 'blender_build_hash', 'blender_binary',
                        'blender_binary_sha256', 'python_runtime', 'python_runtime_sha256',
                        'fbx_addon_file', 'background', 'autoexec_disabled', 'source_saved', 'rendered',
                        'observed_host', 'sys_platform', 'pointer_bits'), 'owned Blender probe')
    c.exact(probe['schema'], PROBE_SCHEMA, 'native probe schema')
    compare_native_host(host['native_observed_host'], probe['observed_host'])
    compare_cross_role(ctx.host.expected_host, probe['observed_host'])
    expected = {'blender_version': [4, 3, 2], 'blender_build_hash': host['blender_build_hash'],
                'blender_binary': host['tools']['blender']['path'],
                'blender_binary_sha256': host['tools']['blender']['sha256'],
                'python_runtime': host['tools']['blender_python_runtime']['path'],
                'python_runtime_sha256': host['tools']['blender_python_runtime']['sha256'],
                'fbx_addon_file': str(ctx.root('blender_bundle')/host['addon_relative']/'__init__.py'),
                'background': True, 'autoexec_disabled': True, 'source_saved': False, 'rendered': False,
                'sys_platform': 'win32', 'pointer_bits': 64}
    for name, value in expected.items():
        c.exact(probe[name], value, 'owned native probe binding')
    command = probe_command(host['tools']['blender']['path'], pins['probe_source'].path, pins['probe'].path)
    context = c.strict_json(pins['command_context'].path, cap=16*1024)
    c.exact_keys(context, ('schema', 'label', 'argv', 'cwd', 'executable', 'environment_sha256', 'host'), 'probe command context')
    c.exact(context['schema'], 'rust-duty-onehand-controller-command/v1', 'probe command schema')
    c.exact(context['label'], 'blender-host-observation', 'probe command label')
    c.exact(context['argv'], command, 'probe command argv')
    c.exact(context['cwd'], str(ctx.candidate_root), 'probe command cwd')
    c.sha(context['environment_sha256'])
    c.exact(context['environment_sha256'], host['controller_environment_sha256'], 'probe command environment')
    initial_host = c.HostBuildBinding.parse(context['host'])
    c.exact(initial_host.runner_id, ctx.host.runner_id, 'probe runner')
    c.exact(initial_host.run_id, ctx.host.run_id, 'probe run')
    c.exact(initial_host.expected_host, ctx.host.expected_host, 'probe outer host')
    tool = lambda name: {**host['tools'][name], 'bytes': Path(host['tools'][name]['path']).stat().st_size}
    c.exact(context['executable'], tool('blender'), 'probe command executable')
    binding = {'runner_id': ctx.host.runner_id, 'run_id': ctx.host.run_id,
               'build_sha256': initial_host.build_sha256, 'context_sha256': c.digest(context),
               'observed_host': ctx.host.expected_host, 'owner_lock': str(ctx.owner_lock),
               'environment_sha256': host['native_environment_sha256'],
               'environment_keys': host['native_environment_keys']}
    limits = adapter.Limits(stdout_mode='bytes', max_stdout_bytes=4*MIB, max_stderr_bytes=MIB)
    process_validator(adapter, pins['process_terminal'].path.parent,
                      {'command': command, 'cwd': str(ctx.candidate_root), 'host_binding': binding,
                       'limits': dataclasses.asdict(limits), 'supervisor_python': tool('python'),
                       'executable': tool('blender'), 'rows': 0})
    for pin in pins.values():
        pin.verify()
    return probe
