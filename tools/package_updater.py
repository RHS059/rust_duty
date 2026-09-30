#!/usr/bin/env python3
"""Package only the bootstrap/helper, user-run setup scripts, docs and actual dependency notices."""
import argparse
from pathlib import Path
import shutil
import subprocess


def package(root, binaries, output, expected_key=None):
    extension = ".exe" if (binaries / "rust-duty-launcher.exe").is_file() else ""
    launcher = binaries / f"rust-duty-launcher{extension}"
    helper = binaries / f"rust-duty-release-sign{extension}"
    trust = subprocess.check_output([str(launcher.resolve()), "trust-status"], text=True).strip()
    expected = f"CONFIGURED {expected_key}" if expected_key else "UNCONFIGURED"
    if trust != expected:
        raise RuntimeError("compiled bootstrap signing trust differs from requested artifact trust")
    output.mkdir(parents=True, exist_ok=True)
    files = [(launcher, launcher.name), (helper, helper.name),
             (root / "tools/setup-release-signing.ps1", "setup-release-signing.ps1"),
             (root / "tools/publish-approved-weapon.ps1", "publish-approved-weapon.ps1"),
             (root / "docs/UPDATER.md", "UPDATER.md"), (root / "docs/SIGNING_SETUP.md", "SIGNING_SETUP.md"),
             (root / "LICENSE", "LICENSE"),
             (root / "updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt", "THIRD_PARTY_UPDATER_LICENSES.txt"),
             (root / "updater/notices/UPDATER_DEPENDENCIES.json", "UPDATER_DEPENDENCIES.json")]
    for source, name in files:
        if not source.is_file(): raise FileNotFoundError(source)
        shutil.copy2(source, output / name)
    (output / "BOOTSTRAP_TRUST.txt").write_text(trust + "\n", encoding="utf-8")
    if expected_key:
        (output / "release-public-key.hex").write_text(expected_key + "\n", encoding="utf-8")
        message = "This bootstrap pins the approved public key. Open the launcher to install/check signed releases and start the game once.\n"
    else:
        message = "UNCONFIGURED development/bootstrap-setup build. It cannot download production updates yet. Run the signing setup personally only after approval, then obtain the reviewed pinned release bootstrap.\n"
    (output / "START_HERE.txt").write_text(message + "Signing setup is for the release owner only; players do not create signing keys. See SIGNING_SETUP.md if you are that owner. Never send a private signing key to chat. No game assets or private data are included in this bootstrap package.\n", encoding="utf-8")
    print(f"Packaged {output}: {trust}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--bin-dir", type=Path, default=Path("updater/target/release"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-public-key")
    args = parser.parse_args()
    package(args.root, args.bin_dir, args.output, args.expected_public_key)
