"""Paste/run only in new cells of the verified private Colab notebook after coordinator approval.

Define the observed allocation start outside the worker. Importing this template
allocates nothing, fetches nothing and launches nothing. Call launch explicitly.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import urllib.request

# Replaced from reviewed bytes when the proposal is frozen; never infer latest.
EXPECTED_FILES = {'prepare_linux_actual_game.py': 'ac77ab291e5fb1abd6607a41793337a9fc51a88dc293db506f8e8ea7154e4296', 'a100_public_build.py': 'a1a30d81cf735aeb8534be3d22979651c0848105f2bf57abdf541885bee9c88e', 'prepare_public_a100.py': 'd9fd04112005f9c98cf6b71b4c7f9d4bb966be77b1e7d10ff41b64b215b92248', 'run_public_a100_matrix.py': '3a4b4a7d58304603bbcacd86e721f3548277762aebfcd4ed5a8e0a7bdb49200d', 'prepare_a100_text_export.py': '30b617651e76747fa241d11d4572bffcb1b0ad771d21b4785c2853e287c6fadf'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate_clock(start, deadline, now=None):
    now = time.time() if now is None else now
    require(all(type(x) in (int, float) and math.isfinite(x) for x in (start, deadline, now)), "Supply observed allocation timestamps")
    require(start <= now < deadline and 0 < deadline - start <= 1800 and deadline - now > 90,
            "Need a deadline within 30 minutes of observed allocation start with export/disconnect time remaining")


def verify_bootstrap(directory):
    expected_names = {'prepare_linux_actual_game.py', 'a100_public_build.py', 'prepare_public_a100.py',
                      'run_public_a100_matrix.py', 'prepare_a100_text_export.py'}
    require(set(EXPECTED_FILES) == expected_names, "Incomplete reviewed bootstrap pin list")
    directory = Path(directory)
    require(not directory.is_symlink() and not any(p.is_symlink() for p in directory.parents), "Linked bootstrap directory")
    require({p.name for p in directory.iterdir()} == expected_names, "Unexpected or missing bootstrap files")
    for name, expected in EXPECTED_FILES.items():
        path = directory / name
        require(re.fullmatch('[0-9a-f]{64}', expected) and path.is_file() and not path.is_symlink()
                and 0 < path.stat().st_size <= 256 * 1024 and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                "Bootstrap hash mismatch: " + name)


def fetch_bootstrap(directory, support_commit):
    require(isinstance(support_commit, str) and re.fullmatch('[0-9a-f]{40}', support_commit), "Supply the newly published immutable support commit")
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, expected in EXPECTED_FILES.items():
        require(re.fullmatch('[a-z0-9_]+\\.py', name), "Invalid bootstrap filename")
        url = 'https://raw.githubusercontent.com/RHS059/rust_duty/' + support_commit + '/tools/' + name
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'RustDutyPublicA100Bootstrap/1'}), timeout=20) as response:
            require(response.status == 200, "Public bootstrap download failed")
            data = response.read(256 * 1024 + 1)
        require(0 < len(data) <= 256 * 1024 and hashlib.sha256(data).hexdigest() == expected, "Public bootstrap bytes differ: " + name)
        (directory / name).write_bytes(data)
    verify_bootstrap(directory)


def process_start(pid):
    try:
        fields = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(') ', 1)[1].split()
        return None if fields[0] in ('Z', 'X') else fields[19]
    except (OSError, IndexError):
        return None


def launch(support_commit, allocation_start_unix, deadline_unix, parent='/content/rust-duty-a100-launches'):
    """Detach one reviewed controller into fresh logs; never run older notebook cells."""
    try:
        validate_clock(allocation_start_unix, deadline_unix)
        require(isinstance(support_commit, str) and re.fullmatch('[0-9a-f]{40}', support_commit), "Immutable support commit required")
        require(Path('/usr/bin/python3.12').is_file(), "Verified distro /usr/bin/python3.12 required")
        parent = Path(parent).absolute()
        require(not parent.is_symlink() and not any(p.is_symlink() for p in parent.parents), "Linked launch parent")
        parent.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix='launch-', dir=parent))
        (root / 'tmp').mkdir()
        def setup_timeout(signum, frame):
            raise TimeoutError('Bootstrap setup deadline; disconnect and delete runtime now')
        require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "Existing process timer is active")
        old = signal.signal(signal.SIGALRM, setup_timeout)
        signal.setitimer(signal.ITIMER_REAL, min(120, deadline_unix - time.time() - 90))
        try:
            fetch_bootstrap(root / 'tools', support_commit)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
        validate_clock(allocation_start_unix, deadline_unix)
        command = ['/usr/bin/python3.12', '-B', str(root / 'tools/prepare_public_a100.py'), '--execute', '--install-system-deps',
                   '--runs-root', str(root / 'runs'), '--support-commit', support_commit,
                   '--allocation-start-unix', str(allocation_start_unix), '--deadline-unix', str(deadline_unix), '--export-reserve-seconds', '90']
        env = {'PATH': '/usr/bin:/bin:/usr/local/bin:/usr/lib64-nvidia/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'TMPDIR': str(root / 'tmp'), 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        if 'HOME' in os.environ:
            env['HOME'] = os.environ['HOME']
        with (root / 'controller.log').open('xb') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        value = {'schema': 'rust-duty-a100-launch/v1', 'launch_root': str(root), 'controller_pid': process.pid,
                 'controller_start_ticks': process_start(process.pid), 'support_commit': support_commit,
                 'allocation_start_unix': allocation_start_unix, 'deadline_unix': deadline_unix,
                 'bootstrap_sha256': EXPECTED_FILES, 'command': command, 'log': str(root / 'controller.log')}
        (root / 'LAUNCH.json').write_text(json.dumps(value, indent=2) + '\n')
        return value
    except BaseException:
        print('LAUNCH_STOPPED: save available logs, then disconnect and delete the Colab runtime now; shutdown is not confirmed.', flush=True)
        raise


def poll(launch_root):
    root = Path(launch_root)
    launch = json.loads((root / 'LAUNCH.json').read_text())
    actual_start = process_start(launch['controller_pid'])
    running = actual_start is not None and actual_start == launch['controller_start_ticks']
    results = list((root / 'runs').glob('run-*/RESULT.json')) if (root / 'runs').exists() else []
    require(len(results) <= 1, 'Unexpected multiple task run roots')
    value = {'controller_running': running, 'launch_root': str(root), 'log': str(root / 'controller.log'),
             'remaining_allocation_seconds': launch['deadline_unix'] - time.time()}
    if results:
        value['run_root'] = str(results[0].parent)
        value['result'] = json.loads(results[0].read_text())
    if not running:
        value['next'] = 'Preserve evidence-only export or bounded acknowledged notebook text, then disconnect/delete runtime; never wait for budget expiry.'
    return value
