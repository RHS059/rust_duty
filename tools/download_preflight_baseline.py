#!/usr/bin/env python3
"""Download the fixed Windows 0.1.9 preflight baseline with bounded retries.

Only explicit transient GitHub HTTP failures are retried. Each attempt starts
empty; raw gh diagnostics (including redirect URLs) are never printed. The
workflow must still run release_update.py verify before using these files.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import time


ASSETS = ('rust-duty-0.1.9-x86_64-pc-windows-msvc.rdb',
          'update-x86_64-pc-windows-msvc.json')
RETRY_DELAYS = (2, 4, 8)
TRANSIENT_HTTP = {500, 502, 503, 504}
ATTEMPT_TIMEOUT_SECONDS = 300


class DownloadError(Exception):
    """A fixed/sanitized diagnostic safe for CI logs."""


def download(output):
    output = Path(output)
    if output.is_symlink():
        raise DownloadError('Preflight baseline requires a fresh directory.')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise DownloadError('Preflight baseline requires an empty directory.')

    for attempt in range(len(RETRY_DELAYS) + 1):
        # gh may finish one asset and leave the other partial. Never retry into
        # those files or delete anything outside our own temporary directory.
        with tempfile.TemporaryDirectory(prefix='.download-', dir=output) as directory:
            staging = Path(directory)
            command = ['gh', 'release', 'download', 'v0.1.9',
                       '--repo', 'RHS059/rust_duty', '--dir', str(staging)]
            for name in ASSETS:
                command.extend(['--pattern', name])
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', check=False,
                                    timeout=ATTEMPT_TIMEOUT_SECONDS)
            if result.returncode == 0:
                if not all((staging / name).is_file() and
                           not (staging / name).is_symlink() and
                           (staging / name).stat().st_size > 0 for name in ASSETS):
                    raise DownloadError('Preflight baseline download did not produce both assets.')
                for name in ASSETS:
                    (staging / name).replace(output / name)
                return
            statuses = {int(code) for code in re.findall(r'\bHTTP\s+(\d{3})\b', result.stderr)}

        # Fail closed on access denial, missing assets, other statuses and
        # unknown/transport errors. A 5xx elsewhere must not hide a 4xx.
        status = ', '.join(f'HTTP {code}' for code in sorted(statuses)) or 'unclassified error'
        if not statuses or not statuses <= TRANSIENT_HTTP:
            raise DownloadError(f'Preflight baseline download failed ({status}); no retry.')
        if attempt == len(RETRY_DELAYS):
            raise DownloadError(f'Preflight baseline download failed ({status}); retries exhausted.')
        delay = RETRY_DELAYS[attempt]
        print(f'Preflight baseline download failed ({status}); retrying in {delay}s.', flush=True)
        time.sleep(delay)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        download(args.output)
    except DownloadError as error:
        print(str(error))
        return 1
    except Exception:
        # OS/process exceptions can also contain URLs or credentials.
        print('Preflight baseline download failed; no retry for a local or process error.')
        return 1
    print('Preflight baseline downloaded; manifest and bundle verification follows.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
