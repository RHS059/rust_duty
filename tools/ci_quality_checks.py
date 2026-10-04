#!/usr/bin/env python3
"""Run independent complete-build checks concurrently without omitting checks.

Game Cargo commands remain sequential within one target directory. The updater
has its own manifest/target directory; Python tests use isolated fixtures. Every
lane must pass before CI can stage or upload the complete game. Logs and timings
identify failures instead of hiding them behind a background shell process.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


def pipelines(python=sys.executable):
    return {
        'python': [[python, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_*.py', '-v']],
        'game': [
            ['cargo', 'clippy', '--locked', '--all-targets', '--', '-D', 'warnings'],
            ['cargo', 'test', '--locked'],
            ['cargo', 'build', '--locked', '--release'],
        ],
        'updater': [
            ['cargo', 'fmt', '--manifest-path', 'updater/Cargo.toml', '--all', '--', '--check'],
            ['cargo', 'clippy', '--manifest-path', 'updater/Cargo.toml', '--locked', '--all-targets', '--', '-D', 'warnings'],
            ['cargo', 'test', '--manifest-path', 'updater/Cargo.toml', '--locked'],
        ],
    }


def run_lane(name, commands, root, output, runner=None):
    started = time.monotonic()
    report = {'lane': name, 'commands': [], 'returncode': 0}
    with (output / f'{name}.log').open('w', encoding='utf-8') as log:
        for command in commands:
            print(f'[{name}] START {command!r}', flush=True)
            begin = time.monotonic()
            if runner is not None:
                code = runner(command)
            else:
                with subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      encoding='utf-8', errors='replace') as process:
                    for line in process.stdout:
                        log.write(line)
                        print(f'[{name}] {line}', end='', flush=True)
                    code = process.wait()
            duration = time.monotonic() - begin
            report['commands'].append({'argv': command, 'seconds': duration, 'returncode': code})
            print(f'[{name}] END code={code} seconds={duration:.3f}', flush=True)
            if code:
                report['returncode'] = code
                break
    report['seconds'] = time.monotonic() - started
    return report


def run_all(root, output, lanes=None, runner=None):
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'lanes': []}
    lanes = pipelines() if lanes is None else lanes
    with ThreadPoolExecutor(max_workers=len(lanes)) as executor:
        futures = {name: executor.submit(run_lane, name, commands, root, output, runner)
                   for name, commands in lanes.items()}
        for name, future in futures.items():
            try:
                report['lanes'].append(future.result())
            except Exception as error:
                report['lanes'].append({'lane': name, 'returncode': 1, 'error': str(error)})
    report['seconds'] = time.monotonic() - started
    report['passed'] = all(lane['returncode'] == 0 for lane in report['lanes'])
    (output / 'timings.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    result = run_all(root, root / 'evidence/quality-checks')
    raise SystemExit(0 if result['passed'] else 1)
