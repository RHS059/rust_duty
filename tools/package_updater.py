#!/usr/bin/env python3
"""Stage the standalone GitHub-trusting launcher and its public notices."""
import argparse
from pathlib import Path
import shutil
import subprocess


def package(root, binaries, output):
    extension = '.exe' if (binaries / 'rust-duty-launcher.exe').is_file() else ''
    launcher = binaries / f'rust-duty-launcher{extension}'
    trust = subprocess.check_output([str(launcher.resolve()), 'trust-status'], text=True).strip()
    if trust != 'GITHUB_HTTPS_SHA256 RHS059/rust_duty':
        raise RuntimeError('launcher does not contain the approved fixed GitHub trust boundary')
    output.mkdir(parents=True, exist_ok=True)
    for source, name in [
        (launcher, f'RustDuty{extension}'),
        (root / 'LICENSE', 'LICENSE'),
        (root / 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt', 'THIRD_PARTY_UPDATER_LICENSES.txt'),
        (root / 'updater/notices/UPDATER_DEPENDENCIES.json', 'UPDATER_DEPENDENCIES.json'),
        (root / 'docs/UPDATER.md', 'UPDATER.md'),
    ]:
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output / name)
    (output / 'START_HERE.txt').write_text(
        'Run RustDuty once and choose your existing game folder when asked. '
        'It installs the stable launcher there and preserves local models and settings. '
        'Use that launcher afterward for automatic GitHub update checks and downloads. '
        'Pause, resume, cancel and restart are available in its window. '
        'The release channel must contain a published game version before a download can occur.\n\n'
        'This launcher trusts RHS059/rust_duty over HTTPS and verifies payload size and SHA256. '
        'It does not require signing keys. GitHub repository/account compromise is within that trust boundary. '
        'No private game assets are included here. The launcher itself is also a standalone release asset; '
        'players do not need this CI artifact ZIP for subsequent game updates.\n', encoding='utf-8')
    (output / 'BOOTSTRAP_TRUST.txt').write_text(trust + '\n', encoding='utf-8')
    print(f'Packaged {output}: {trust}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--bin-dir', type=Path, default=Path('updater/target/release'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.root, args.bin_dir, args.output)
