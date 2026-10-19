"""Publish the single reopened canonical BLEND and its descriptive inventories."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

BRANCH = 'aella/onehand-windows-inputs-20261018'
OUTPUTS = {
    'weapon_animations.blend': 'assets/authoring/weapon_animations.blend',
    'EXPORT_MANIFEST.json': 'assets/authoring/weapon_animations.export.json',
    'ALL_ANIMATION_INVENTORY.json': 'assets/authoring/weapon_animations.inventory.json',
    'WEAPON_LIBRARY_REOPEN_VERIFICATION.json': 'assets/authoring/weapon_animations.verification.json',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def publish(root, work, head, base):
    token = os.environ.pop('CANONICAL_PUSH_TOKEN', '')
    require(token, 'workflow push token unavailable')
    require(git(root, 'rev-parse', 'HEAD') == head, 'unexpected checkout head')
    require(git(root, 'rev-parse', 'HEAD^') == base, 'unexpected bootstrap parent')
    require(not git(root, 'status', '--porcelain'), 'checkout must be clean')
    require(git(root, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0] == head, 'branch advanced')
    result = json.loads((work / 'WEAPON_LIBRARY_REOPEN_VERIFICATION.json').read_text())
    require(result.get('status') == 'PASS' and result.get('source_files_unchanged') is True, 'reopen verification did not pass')
    for key, expected in [('source_sets', 9), ('scene_count', 10), ('action_count', 666), ('export_clip_count', 67), ('packed_image_count', 27)]:
        require(result.get(key) == expected, 'canonical inventory differs: ' + key)
    manifest = json.loads((work / 'EXPORT_MANIFEST.json').read_text())
    require(manifest.get('schema') == 'rust-duty-weapon-nla/v1' and len(manifest.get('clips', [])) == 67, 'invalid export manifest')
    require(len({clip['id'] for clip in manifest['clips']}) == 67, 'duplicate export ID')
    expected = json.loads((Path(__file__).resolve().parent / 'expected_export_manifest.json').read_text())
    require(manifest == expected, 'export names, object selection or frame metadata differ from reviewed manifest')
    identities = {}
    for name, destination in OUTPUTS.items():
        source = work / name
        require(source.is_file() and not source.is_symlink(), 'missing ordinary output')
        require(0 < source.stat().st_size < 100 * 1024 * 1024, 'output outside GitHub file-size bound')
        target = root / destination
        require(not target.exists() and not target.is_symlink(), 'canonical destination already exists')
        require(not any(parent.is_symlink() for parent in target.parents), 'symlink destination')
        with source.open('rb') as stream:
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        identities[destination] = {'bytes': source.stat().st_size, 'sha256': sha256}
    for name, destination in OUTPUTS.items():
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / name, target)
        with target.open('rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == identities[destination]['sha256'], 'copy identity differs')
    paths = sorted(OUTPUTS.values())
    git(root, 'add', '-f', '--', *paths)
    require(sorted(git(root, 'diff', '--cached', '--name-only').splitlines()) == paths, 'staged files exceed canonical allowlist')
    require(git(root, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0] == head, 'branch advanced before commit')
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=github-actions[bot]',
                    '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                    'commit', '-m', 'Publish complete canonical weapon animation BLEND and NLA inventory'], check=True)
    commit = git(root, 'rev-parse', 'HEAD')
    require(git(root, 'rev-parse', 'HEAD^') == head, 'commit parent differs')
    require(sorted(git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()) == paths, 'commit files exceed allowlist')
    environment = dict(os.environ)
    environment.update({'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
                        'GIT_CONFIG_VALUE_0': 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode(),
                        'GIT_TERMINAL_PROMPT': '0'})
    subprocess.run(['git', '-C', str(root), 'push', 'origin', 'HEAD:refs/heads/' + BRANCH], check=True, env=environment)
    require(git(root, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split()[0] == commit, 'publication readback failed')
    print(json.dumps({'canonical_commit': commit, 'parent': head, 'files': identities,
                      'next_step': 'Publish permanent canonical-BLEND per-NLA export workflow; no new game success claimed.'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--expected-base', required=True)
    args = parser.parse_args()
    publish(args.root.resolve(), args.work.resolve(), args.expected_head, args.expected_base)
