"""Additive, bounded public diagnostics for an already-failed owned command.

This is not an admission path. It never launches, retries, edits receipts, or
changes the original exception. Seals establish local byte consistency, not
host attestation. Raw output, argv, paths, environment, locals and geometry
never enter the public projection. Source text comes only from exact reviewed
public source bytes, never from a traceback's displayed source/exception text.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import io
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys

import workflow_core as w

MIB = 1024**2
RECEIPT_CAP = MIB
STREAM_CAPS = {'stdout': 8*MIB, 'stderr': MIB, 'samples': 8*MIB}
SOURCE_CAP = MIB
PUBLIC_CAP = 48*1024
MAX_FRAMES = 24
MAX_ERRORS = 8
MAX_LINE = 4096
MAX_LINES = 50000
COMMANDS = frozenset(('source-replay', 'blender-ensurepip', 'blender-pillow-install',
                     'blender-host-observation', 'rustc-version', 'cargo-version',
                     'cargo-vendor', 'cargo-metadata', 'cargo-build', 'python-contract'))
STAGES = dict((name, 67 if name.endswith('chunk') or name == 'chunk-import' else
               12 if name == 'block' else None) for name, _ in w.sequence())
ERRORS = frozenset(('AssertionError', 'ValueError', 'TypeError', 'RuntimeError',
                    'KeyError', 'IndexError', 'AttributeError', 'ImportError',
                    'ModuleNotFoundError', 'FileNotFoundError', 'PermissionError',
                    'OSError', 'MemoryError', 'RecursionError', 'SyntaxError',
                    'SystemExit', 'AdapterError', 'ContextError', 'ExceptionGroup',
                    'BaseExceptionGroup'))
REASONS = frozenset(('child_exit_failure', 'launch_failure', 'own_child_timeout',
                    'initial_available_memory_guard', 'initial_disk_retention_guard',
                    'own_child_rss_ceiling', 'own_child_disk_reserve_guard',
                    'resource_observation_failure', 'executable_changed',
                    'executable_recheck_failure', 'consumer_failure',
                    'consumer_incomplete', 'reader_cleanup_incomplete',
                    'owned_cleanup_failure', 'supervisor_cleanup_incomplete',
                    'owner_lock_changed', 'transport_receipt_failure',
                    'stdout_reader_failure', 'stderr_reader_failure',
                    'stdout_durability_failure', 'stderr_durability_failure'))
FRAME = re.compile(r'^  File "([^"\r\n]{1,2048})", line ([1-9][0-9]{0,7})(?:, in [^\r\n]{1,256})?$')
EXCEPTION = re.compile(r'^([A-Za-z_][A-Za-z_0-9.]{0,127})(?:: (.*))?$')
TRACE_START = 'Traceback (most recent call last):'
TRACE_LINKS = frozenset(('During handling of the above exception, another exception occurred:',
                         'The above exception was the direct cause of the following exception:'))


def identity(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def check(condition):
    if not condition:
        raise ValueError('diagnostic data unavailable')


def snapshot(path, cap):
    """Bound reads, reject redirects, and bind the same open regular file twice."""
    path = w.ordinary(path, True)
    before_path = path.lstat()
    check(stat.S_ISREG(before_path.st_mode))
    check(before_path.st_size <= cap)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        check(stat.S_ISREG(before.st_mode))
        check((before.st_dev, before.st_ino) == (before_path.st_dev, before_path.st_ino))
        raw = stream.read(cap+1)
        after = os.fstat(stream.fileno())
    w.ordinary(path, True)
    after_path = path.lstat()
    key = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    check(key(before) == key(after) == key(after_path) and len(raw) == after.st_size <= cap)
    return raw


def parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            check(key not in value)
            value[key] = item
        return value
    def bad(_):
        raise ValueError('invalid diagnostic JSON')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad)
    check(type(value) is dict)
    return value


def role(kind, label, index):
    if kind == 'command' and type(label) is str and label in COMMANDS and index is None:
        return {'kind': kind, 'role': label, 'stage': None, 'index': None}
    if kind == 'native-stage' and type(label) is str and label in STAGES:
        cap = STAGES[label]
        if (cap is None and index is None) or (type(index) is int and cap is not None and 0 <= index < cap):
            return {'kind': kind, 'role': 'native-stage', 'stage': label, 'index': index}
    return {'kind': 'unrecognized', 'role': None, 'stage': None, 'index': None}


def expected(adapter, target, argv, cwd, binding, limits, context_path, context_sha256, executable):
    """Private expected request supplied by the caller before launching the leaf."""
    try:
        return {'target': target, 'context_path': context_path, 'executable': dict(executable),
                'context_file_sha256': context_sha256,
                'request': {'command': list(argv), 'cwd': str(cwd),
                            'host_binding': binding.record(), 'limits': dataclasses.asdict(limits),
                            'supervisor_python': adapter.file_identity(sys.executable)}}
    except BaseException:
        return {}


def native_expected(packages, ctx, config):
    try:
        adapter, planner, environment = packages.adapter, packages.native.planner, config['native_environment']
        binding = adapter.HostBinding(runner_id=ctx.host.runner_id, run_id=ctx.host.run_id,
                    build_sha256=ctx.host.build_sha256, expected_host=ctx.host.expected_host,
                    environment=environment, owner_lock=str(ctx.owner_lock), context_sha256=ctx.context_sha256)
        argv = planner.native_argv(ctx)
        return expected(adapter, ctx.transport_output, argv, ctx.candidate_root, binding,
                        planner.process_limits(adapter), ctx.path, w.sha(ctx.path), w.record(argv[0]))
    except BaseException:
        return {}


def _reference(root, ref, name, cap):
    check(type(ref) is dict and ref.get('path') == name)
    check(type(ref.get('bytes')) is int and 0 <= ref['bytes'] <= cap)
    check(type(ref.get('sha256')) is str and re.fullmatch('[0-9a-f]{64}', ref['sha256']) is not None)
    raw = snapshot(root/name, min(cap, ref['bytes']))
    check(identity(raw) == {'sha256': ref['sha256'], 'bytes': ref['bytes']})
    return raw


def _request_bound(value, request):
    check(value.get('schema') == 'rust-duty-owned-process/v1')
    for key, wanted in request.items():
        check(type(value.get(key)) is type(wanted) and canonical(value[key]) == canonical(wanted))


def sealed(adapter, state, command_role):
    """Read a bounded, self-consistent failure snapshot; never admits a process."""
    check(command_role['kind'] != 'unrecognized')
    root = w.ordinary(state['target'], True)
    wanted_label = command_role['role'] if command_role['kind'] == 'command' else command_role['stage']
    if command_role['index'] is not None:
        wanted_label += '-%03d' % command_role['index']
    check(root.name == wanted_label and root.parent.name == 'process')
    context_raw = snapshot(state['context_path'], RECEIPT_CAP)
    check(identity(context_raw)['sha256'] == state['context_file_sha256'])
    context = parse(context_raw)
    request = state['request']
    check(w.digest(context) == request['host_binding']['context_sha256'])
    if command_role['kind'] == 'command':
        check(context.get('schema') == 'rust-duty-onehand-controller-command/v1')
        check(context.get('label') == wanted_label)
        check(context.get('argv') == request['command'] and context.get('cwd') == request['cwd'])
    else:
        check(context.get('stage') == command_role['stage'] and context.get('stage_id') == wanted_label)
        check(type(context.get('index')) is type(command_role['index']) and context['index'] == command_role['index'])
    seal_raw = snapshot(root/'terminal.sha256.json', RECEIPT_CAP)
    terminal_raw = _reference(root, parse(seal_raw), 'terminal.json', RECEIPT_CAP)
    terminal = parse(terminal_raw)
    _request_bound(terminal, request)
    executable = state['executable']
    check(executable['path'] == request['command'][0])
    if terminal.get('executable_before') is not None:
        check(all(terminal['executable_before'].get(k) == v for k, v in executable.items()))
    else:
        check(terminal.get('started') is False)
    limits = adapter.Limits(**terminal['limits']).validate()
    refs = {'context': identity(context_raw), 'request': identity(canonical(request)),
            'terminal': identity(terminal_raw), 'terminal_seal': identity(seal_raw)}
    records = {}
    check(terminal.get('attempt') is not None)
    for key, name in (('attempt', 'attempt.json'), ('started_record', 'started.json'),
                      ('transport_record', 'transport.json')):
        ref = terminal.get(key)
        refs[key] = None
        if ref is not None:
            raw = _reference(root, ref, name, min(RECEIPT_CAP, limits.max_receipt_bytes))
            records[key] = parse(raw)
            _request_bound(records[key], request)
            refs[key] = identity(raw)
    check(records['attempt'].get('state') == 'prepared')
    if 'started_record' in records:
        start = records['started_record']
        check(start.get('state') == 'started' and start.get('attempt') == terminal['attempt'])
        for key in ('pid', 'executable_before'):
            check(canonical(start.get(key)) == canonical(terminal.get(key)))
    if 'transport_record' in records:
        transport = records['transport_record']
        check(transport.get('state') == 'transport_stopped')
        # Consumer completion/reason may change during __exit__; these process
        # lifecycle/linkage facts may not. Contradictions are unavailable.
        for key in ('started', 'pid', 'exit_code', 'cleanup_complete',
                    'constructor_cleanup_complete', 'windows_job_empty_verified',
                    'executable_before', 'executable_after', 'attempt', 'started_record'):
            check(canonical(transport.get(key)) == canonical(terminal.get(key)))
    check(type(terminal.get('started')) is bool)
    check(not terminal['started'] or refs['started_record'] is not None or terminal.get('constructor_cleanup_complete') is not None)
    check(type(terminal.get('completed')) is bool)
    check(terminal.get('state') in ('completed', 'partial', 'failed'))
    check(type(terminal.get('exit_code')) is int or terminal.get('exit_code') is None)
    check(terminal.get('exit_code') is None or -(2**32) <= terminal['exit_code'] <= 2**32-1)
    for key in ('cleanup_complete', 'consumer_complete', 'timed_out'):
        check(type(terminal.get(key)) is bool)
    for key in ('windows_job_empty_verified', 'constructor_cleanup_complete'):
        check(terminal.get(key) is None or type(terminal[key]) is bool)
    check(set(terminal.get('streams', {})) == set(STREAM_CAPS))
    streams = {}
    for key, cap in STREAM_CAPS.items():
        maximum = getattr(limits, 'max_'+key+'_bytes')
        raw = _reference(root, terminal['streams'][key], key+('.jsonl' if key == 'samples' else '.bin'), min(cap, maximum))
        refs[key] = identity(raw)
        if key != 'samples':
            streams[key] = raw
    # A completed receipt may accompany a later validator failure. It still
    # cannot turn the enclosing exception into success or a native proof.
    if terminal['completed']:
        check(terminal['state'] == 'completed' and terminal['exit_code'] == 0)
        check(terminal['cleanup_complete'] and terminal['consumer_complete'] and not terminal['timed_out'])
        check(terminal.get('resource_stop_reason') is None and terminal.get('executable_before') == terminal.get('executable_after'))
        for item in terminal['streams'].values():
            check(item.get('eof_observed') is True and item.get('truncated') is False)
            check(item.get('observed_bytes') == item['bytes'] and item.get('observed_sha256') == item['sha256'])
        if request['host_binding']['observed_host']['system'] == 'Windows':
            check(terminal['windows_job_empty_verified'] is True)
    else:
        check(terminal['state'] != 'completed')
    # Re-read every public source of identity after collecting the snapshot.
    # Mutation makes diagnostics unavailable, never a new native failure/pass.
    check(snapshot(state['context_path'], RECEIPT_CAP) == context_raw)
    check(snapshot(root/'terminal.sha256.json', RECEIPT_CAP) == seal_raw)
    check(snapshot(root/'terminal.json', RECEIPT_CAP) == terminal_raw)
    lifecycle = {key: terminal.get(key) for key in
                 ('state', 'started', 'completed', 'exit_code', 'cleanup_complete',
                  'consumer_complete', 'constructor_cleanup_complete',
                  'windows_job_empty_verified', 'timed_out')}
    reason = terminal.get('resource_stop_reason')
    lifecycle['reason'] = reason if type(reason) is str and reason in REASONS else None
    lifecycle['reason_sha256'] = None if reason is None else identity(canonical(reason))['sha256']
    return refs, lifecycle, streams


def path_key(value):
    """Exact absolute Windows/POSIX identity, never a basename/suffix match."""
    check(type(value) is str and '\0' not in value and len(value) <= 2048)
    if re.match(r'^[A-Za-z]:[\\/]', value):
        check(not any(p in ('.', '..') or p.endswith((' ', '.')) or ':' in p for p in re.split(r'[\\/]', value[3:])))
        return ('windows', ntpath.normcase(value.replace('/', '\\')))
    check(value.startswith('/') and not value.startswith('//'))
    check(not any(p in ('.', '..') for p in value.split('/')))
    return ('posix', value)


def source_index(roots):
    value = parse(snapshot(w.HERE/'DIAGNOSTIC_SOURCE_PINS.json', MIB))
    check(value.get('schema') == 'rust-duty-public-diagnostic-source-pins/v1')
    rows = value['files']
    check(type(rows) is list and len(rows) <= 256)
    result = {}
    for row in rows:
        source_id, relative, root_role = row['source_id'], row['relative_path'], row['root_role']
        check(re.fullmatch(r'[A-Za-z0-9_./-]{1,240}', source_id) is not None)
        check(not any(p in ('', '.', '..') for p in relative.split('/')) and '\\' not in relative and ':' not in relative)
        base = w.HERE if root_role == 'orchestration' else roots.get(root_role)
        if base is None:
            continue
        path = Path(base)/relative
        key = path_key(str(path))
        check(key not in result)
        result[key] = (path, row)
    return result


def _static_template(node):
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(x.value if isinstance(x, ast.Constant) and type(x.value) is str else '<dynamic>' for x in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static_template(node.left), _static_template(node.right)
        if left is not None or right is not None:
            return (left if left is not None else '<dynamic>') + (right if right is not None else '<dynamic>')
    return None


def source_frame(filename, line, registry):
    found = registry.get(path_key(filename))
    if found is None:
        return None
    path, pin = found
    raw = snapshot(path, SOURCE_CAP)
    check(identity(raw) == {'sha256': pin['sha256'], 'bytes': pin['bytes']})
    text = raw.decode('utf-8')
    lines = text.splitlines()
    check(1 <= line <= len(lines))
    templates = []
    for node in ast.walk(ast.parse(text)):
        if not getattr(node, 'lineno', 0) <= line <= getattr(node, 'end_lineno', 0):
            continue
        message = None
        if isinstance(node, ast.Assert):
            message = node.msg
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            message = node.exc.args[0]
        elif isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == 'require') or
                                           (isinstance(node.func, ast.Attribute) and node.func.attr == 'require')) and len(node.args) >= 2:
            message = node.args[1]
        template = _static_template(message)
        if template and len(template) <= 240 and all(32 <= ord(c) <= 126 for c in template):
            # Source templates are public declarations, not observed values.
            # Never permit an opaque/high-entropy literal or credential pattern.
            if not re.search(r'(?i)(?:password|secret|token|api.?key)\s*[:=]|[A-Za-z0-9+/=_-]{48,}|(?:[A-Za-z]:\\|https?://)', template):
                templates.append(template)
    return {'source_id': pin['source_id'], 'source_sha256': pin['sha256'], 'line': line,
            'source_line_sha256': identity(lines[line-1].encode())['sha256'],
            'static_error_templates': sorted(set(templates))[:4]}


def traceback_projection(raw, registry):
    """Parse only bounded ordinary Python traceback framing; ignore all locals."""
    frames, errors = [], []
    active = False
    chain = 0
    current_templates = []
    unknown_frames = 0
    truncated = False
    compiler_codes = set()
    stream = io.BytesIO(raw)
    for _ in range(MAX_LINES):
        encoded = stream.readline(MAX_LINE+1)
        if not encoded:
            break
        if len(encoded) > MAX_LINE:
            active = False
            while encoded and not encoded.endswith(b'\n'):
                encoded = stream.readline(MAX_LINE+1)
            continue
        encoded = encoded.rstrip(b'\r\n')
        try:
            line = encoded.decode('utf-8')
        except UnicodeError:
            active = False
            continue
        code = re.match(r'^error\[(E[0-9]{4})\]:', line)
        if code and len(compiler_codes) < 16:
            compiler_codes.add(code[1])
        # ExceptionGroup's fixed ASCII gutter is structure, not source text.
        # A finite number of strips handles nested groups; never strip a path.
        for _ in range(8):
            match = re.match(r'^ {0,12}\| (.*)$', line)
            if match is None:
                break
            line = match[1]
        if line in (TRACE_START, 'Error: Python: '+TRACE_START) or re.fullmatch(r' {0,8}\+ Exception Group Traceback \(most recent call last\):', line):
            active = True
            current_templates = []
            chain += 1
            if chain > MAX_ERRORS:
                truncated = True
                break
            continue
        if re.fullmatch(r' {0,8}[+|]-{3,}(?: [0-9]{1,3} -{3,})?', line):
            active = False
            continue
        if not active:
            continue
        match = FRAME.fullmatch(line)
        if match:
            if len(frames) >= MAX_FRAMES:
                truncated = True
                continue
            try:
                frame = source_frame(match[1], int(match[2]), registry)
            except Exception:
                frame = None
            if frame is None:
                unknown_frames += 1
            else:
                frames.append({'traceback': chain, **frame})
                current_templates.extend(frame['static_error_templates'])
            continue
        if not line or line[:1].isspace():
            continue  # displayed source, caret ranges and locals are untrusted
        match = EXCEPTION.fullmatch(line)
        if match:
            category = match[1] if match[1] in ERRORS else 'unrecognized'
            message = match[2] or ''
            exact = message if message in current_templates and '<dynamic>' not in message else None
            errors.append({'traceback': chain, 'category': category,
                           'exception_line': identity(encoded), 'verified_static_message': exact})
            active = False
        elif line not in TRACE_LINKS:
            active = False
    else:
        truncated = True
    return {'frames': frames, 'exceptions': errors[:MAX_ERRORS], 'unknown_frames': unknown_frames,
            'recognized_rust_error_codes': sorted(compiler_codes),
            'truncated': truncated, 'unrecognized_content': 'hash-only; see enclosing stream identity',
            'source_templates_are_declarations_not_dynamic_values': True}


class _Projection:
    def __init__(self, value):
        self.raw = canonical(value)
        if len(self.raw) > PUBLIC_CAP:
            value = dict(value, tracebacks=None, traceback_status='public-projection-cap')
            self.raw = canonical(value)
        check(len(self.raw) <= PUBLIC_CAP)


def capture_failure(error, *, kind, label, index=None, adapter=None, state=None, roots=None):
    """Best effort only. Call inside except, then use bare raise, never raise us."""
    try:
        command_role = role(kind, label, index)
        value = {'schema': 'rust-duty-owned-failure-public/v1', **command_role,
                 'diagnostic_status': 'unavailable', 'receipt_binding_verified': False,
                 'native_proof': False, 'original_outcome': 'failed',
                 'original_error_category': type(error).__name__ if type(error).__name__ in ERRORS else 'unrecognized',
                 'original_error_sha256': identity(str(error).encode())['sha256'],
                 'identities': None, 'lifecycle': None, 'tracebacks': None}
        try:
            refs, lifecycle, streams = sealed(adapter, state or {}, command_role)
            value.update(diagnostic_status='sealed-request-bound', receipt_binding_verified=True,
                         identities=refs, lifecycle=lifecycle)
            try:
                registry = source_index(roots or {})
            except Exception:
                registry = {}
            value['tracebacks'] = {key: traceback_projection(raw, registry) for key, raw in streams.items()}
        except Exception:
            pass
        error._onehand_failure_projection = _Projection(value)
    except BaseException:
        pass  # The failure being diagnosed must remain the identical exception.


def public_failure(error):
    try:
        value = getattr(error, '_onehand_failure_projection', None)
        return json.loads(value.raw) if type(value) is _Projection else None
    except BaseException:
        return None
