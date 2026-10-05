#!/usr/bin/env python3
"""Revalidate cached or freshly generated companions against current source inputs."""
import argparse
import json
from pathlib import Path
import package_game
from build_blender_assets import selections


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['reload', 'walk', 'ads', 'directional', 'jump'], required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args()
    package_game.verify(args.root)
    if args.kind == 'jump':
        report = package_game.verify_jump(args.root, args.directory, require_transports=True)
    elif args.kind == 'directional':
        report = package_game.verify_directional(args.root, args.directory, require_transports=True)
    elif args.kind == 'ads':
        report = package_game.verify_ads(args.root, args.directory, require_transports=True)
    elif args.kind == 'walk':
        report = package_game.verify_walk(args.root, args.directory)
    else:
        contract = json.loads((args.root / 'assets/source/reload/source.json').read_text())
        report = {}
        for key, selected in selections(contract):
            directory = args.directory / 'alternates' / key if key else args.directory
            report[key or 'primary'] = package_game.verify_generated_pack(args.root, directory, selected)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
