#!/usr/bin/env python3
"""Run one real-byte fixture case with observed durable progress and a finite budget.

Test-only runner. Never changes updater durability or the production trust source.
660 seconds is the existing 600-second headless diagnostic budget plus60 seconds
for setup/teardown. A timeout fails closed and terminates only this child tree.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CASES = ('full', 'one-file', 'recover-one-file', 'mismatch', 'unusable', 'corrupt-delta')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'evidence/preflight' / args.case
    evidence.mkdir(parents=True, exist_ok=True)
    temporary = evidence / 'runtime'
    temporary.mkdir()
    env = {**os.environ, 'RUST_DUTY_PREFLIGHT_CASE': args.case,
           'RUST_DUTY_PREFLIGHT': str(root / 'preflight'),
           'TMP': str(temporary), 'TEMP': str(temporary), 'TMPDIR': str(temporary)}
    command = ['cargo', 'test', '--manifest-path', 'updater/Cargo.toml', '--locked',
               '--lib', 'tests::actual_windows_release_candidate_preflight',
               '--', '--exact', '--ignored', '--nocapture']
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=root, env=env)
    previous = None
    changed_at = started
    timed_out = False
    with (evidence / 'progress.jsonl').open('w', encoding='utf-8') as log:
        while process.poll() is None:
            now = time.monotonic()
            statuses = []
            for path in temporary.glob(f'*/{args.case}/status.json'):
                try:
                    statuses.append(json.loads(path.read_text()))
                except (OSError, ValueError):
                    pass  # Atomic replacement can briefly race observation.
            if statuses != previous:
                previous, changed_at = statuses, now
            sample = {'case': args.case, 'utc': datetime.now(timezone.utc).isoformat(),
                      'elapsed_seconds': round(now-started, 2),
                      'unchanged_seconds': round(now-changed_at, 2), 'statuses': statuses}
            line = json.dumps(sample)
            log.write(line + '\n'); log.flush()
            print(line, flush=True)
            if now-started >= 660:
                timed_out = True
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   check=False, timeout=30)
                else:
                    process.kill()
                break
            time.sleep(10)
    try:
        code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait(timeout=10)
    result = {'case': args.case, 'passed': code == 0 and not timed_out,
              'exit_code': code, 'timed_out': timed_out,
              'elapsed_seconds': round(time.monotonic()-started, 2)}
    (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(f"Preflight {args.case}: {result}\n")
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
