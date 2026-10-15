#!/usr/bin/env python3
"""Decide which CI areas a pull request touches.

Pushes, manual runs and any change to CI itself (workflows, lockfiles, this
script, the quality-lane runner) select every area, so main always gets the full
suite before a build is used. Pull requests run only the areas their files touch.
"""
import argparse
import os
import re
import subprocess

FULL = re.compile(r'^(\.github/|Cargo\.lock$|updater/Cargo\.lock$|rust-toolchain|'
                  r'tools/ci_changes\.py$|tools/ci_quality_checks\.py$|tools/requirements)')
GAME = re.compile(r'^(src/|examples/|tests/|benches/|build\.rs$|Cargo\.toml$|assets/|ui/)')
RENDER = re.compile(r'^(src/(render|draw|platform|legacy_macroquad)/|src/(graphics_device|hud|field_ui|'
                    r'ui_theme|pause_menu|world_draw|viewmodel_draw)\b|examples/|ui/|Cargo\.toml$)')
AUTHORED = re.compile(r'^(assets/(reload|walk|ads|directional|jump|weapons)/|assets/animations\.cfg$|'
                      r'src/(render/|view_animation|viewmodel|weapon|animation|ads|layered|sim\b)|'
                      r'tools/.*(authored|ads|walk|jump|directional|reload|viewmodel|vrpack|blender|fbx))')
AREAS = ('game', 'tools', 'updater', 'render', 'authored')


def areas(paths, full=False):
    full = full or any(FULL.match(path) for path in paths)
    result = {
        'game': any(GAME.match(path) for path in paths),
        'tools': any(path.startswith('tools/') for path in paths),
        'updater': any(path.startswith('updater/') for path in paths),
        'render': any(RENDER.match(path) for path in paths),
        'authored': any(AUTHORED.match(path) for path in paths),
    }
    if full:
        result = dict.fromkeys(AREAS, True)
    result['any'] = any(result.values())
    result['full'] = full
    return result


def changed_paths(base, head):
    output = subprocess.check_output(['git', 'diff', '--name-only', f'{base}...{head}'], text=True)
    return [line for line in output.splitlines() if line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--event', default=os.environ.get('GITHUB_EVENT_NAME', ''))
    parser.add_argument('--base', default='')
    parser.add_argument('--head', default='HEAD')
    args = parser.parse_args()
    if args.event == 'pull_request' and args.base:
        paths = changed_paths(args.base, args.head)
        result = areas(paths)
        print('\n'.join(paths))
    else:
        result = areas([], full=True)
    lines = [f'{name}={str(value).lower()}' for name, value in result.items()]
    print('\n'.join(lines))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
