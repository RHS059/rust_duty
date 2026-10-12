#!/usr/bin/env python3
"""Execute one compiled renderer-owned example and independently verify evidence."""

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys

import dx12_contract_process


VALIDATORS = {
    'world-primitives': 'verify_world_primitives_contract',
    'frame-identity': 'verify_renderer_frame_identity',
    'ui-theme': 'verify_ui_theme_contract',
    'effects': 'verify_effects_contract',
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, choices=VALIDATORS)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise ValueError('actual DX12 contract examples require Windows')
        validator = importlib.import_module(VALIDATORS[args.fixture]).validate_outputs
        report = dx12_contract_process.run(
            args.executable, args.root, args.evidence, args.output,
            args.timeout, args.fixture, validator)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'DX12 contract example failed: {error}\n')
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
