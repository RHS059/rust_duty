#!/usr/bin/env python3
"""Ordinary asset production commands; compilation is the caller's separate step."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

KINDS = ('reload', 'walk', 'ads', 'directional', 'jump')


def generator_plan(root, work, python, blender, jump_source=None):
    root, work = Path(root), Path(work)
    def py(tool, *args):
        return [str(python), '-B', str(root / 'tools' / tool), *map(str, args)]
    jobs = [{'label': 'game-base-materialize',
             'argv': py('package_game.py', 'materialize', '--root', root)}]
    jobs += [
        {'label': 'game-base-reload-export',
         'argv': py('build_blender_assets.py', '--root', root, '--blender', blender,
                    '--output', work / 'reload')},
        {'label': 'game-base-reload-format-check',
         'argv': py('check_generated_assets.py', '--root', root, '--kind', 'reload',
                    '--directory', work / 'reload/reload'),
         'stage': {'kind': 'reload', 'source': str(work / 'reload/reload'),
                   'destination': str(root / 'assets/reload')}}]
    for kind in KINDS[1:]:
        args = ['--root', root, '--blender', blender,
                '--work', work / kind / 'work', '--output', work / kind / 'runtime']
        if kind == 'jump':
            args += ['--source-dir', jump_source or root / '.jump-source/assets/authoring/jump']
        jobs.append({'label': 'game-base-' + kind + '-export',
                     'argv': py('build_' + kind + '_assets.py', *args)})
        jobs.append({'label': 'game-base-' + kind + '-format-check',
                     'argv': py('check_generated_assets.py', '--root', root, '--kind', kind,
                                '--directory', work / kind / 'runtime'),
                     'stage': {'kind': kind, 'source': str(work / kind / 'runtime'),
                               'destination': str(root / 'assets' / kind)}})
    jobs.append({'label': 'game-base-final-materialize',
                 'argv': py('package_game.py', 'materialize', '--root', root,
                            '--include-walk', '--include-ads', '--include-directional',
                            '--include-jump', '--require-generated')})
    return jobs


def stage_command(root, binary, output, python=sys.executable, update=False):
    command = [str(python), '-B', str(Path(root) / 'tools/package_game.py'), 'stage',
               '--root', str(root), '--binary', str(binary), '--output', str(output),
               '--require-generated']
    if update:
        command.append('--update')
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--jump-source', type=Path)
    args = parser.parse_args()
    print(json.dumps(generator_plan(args.root, args.work, args.python, args.blender,
                                    args.jump_source), indent=2))


if __name__ == '__main__':
    main()
