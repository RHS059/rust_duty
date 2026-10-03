#!/usr/bin/env python3
"""Package only the owner-run signing helper; no game or updater launcher."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
output = root / 'signing-setup-artifact'
output.mkdir(exist_ok=True)
files = {
    'updater/target/release/rust-duty-release-sign.exe': 'rust-duty-release-sign.exe',
    'tools/setup-release-signing.ps1': 'setup-release-signing.ps1',
    'tools/publish-approved-weapon.ps1': 'publish-approved-weapon.ps1',
    'docs/SIGNING_SETUP.md': 'SIGNING_SETUP.md',
    'LICENSE': 'LICENSE',
    'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt': 'THIRD_PARTY_UPDATER_LICENSES.txt',
    'updater/notices/UPDATER_DEPENDENCIES.json': 'UPDATER_DEPENDENCIES.json',
}
for source, name in files.items():
    shutil.copy2(root / source, output / name)
(output / 'START_HERE.txt').write_text(
    'OWNER SIGNING SETUP ONLY. This kit does not install or update the game.\n'
    'Read SIGNING_SETUP.md, then personally run: powershell -NoProfile -File .\\setup-release-signing.ps1\n'
    'An existing authenticated GitHub CLI is required. Only return the public key and setup completed.\n'
    'Never send private key material or shell transcripts to chat. No key operation has run in CI.\n', encoding='utf-8')
print(output)
