"""Commit the validated allowlist with a non-forced, expected-parent branch push."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
from restore import HERE, git, require, verify_file


def publish(root, expected_head):
    token = os.environ.pop('RECOVERY_PUSH_TOKEN', '')
    require(token, 'workflow push token unavailable')
    manifest = json.loads((HERE / 'manifest.json').read_text())
    branch = manifest['branch']
    require(git(root, 'rev-parse', 'HEAD') == expected_head, 'checkout changed')
    require(git(root, 'rev-parse', 'HEAD^') == manifest['base_commit'], 'unexpected recovery parent')
    require(not git(root, 'diff', '--cached', '--name-only'), 'index must be empty')
    paths = []
    for row in manifest['objects']:
        for destination in row['destinations']:
            path = destination['path']
            verify_file(root / path, row)
            require(git(root, 'hash-object', path) == row['git_sha'], 'runtime Git identity changed')
            paths.append(path)
    require(len(paths) == 25 and len(set(paths)) == 25, 'invalid publication allowlist')
    git(root, 'add', '-f', '--', *paths)
    require(set(git(root, 'diff', '--cached', '--name-only').splitlines()) == set(paths), 'staged paths differ')
    remote = git(root, 'ls-remote', 'origin', 'refs/heads/' + branch).split()
    require(remote and remote[0] == expected_head, 'remote branch advanced; do not overwrite')
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=github-actions[bot]',
                    '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                    'commit', '-m', 'Restore exact preserved runtime assets for direct game delivery'], check=True)
    commit = git(root, 'rev-parse', 'HEAD')
    require(git(root, 'rev-parse', 'HEAD^') == expected_head, 'publication parent mismatch')
    require(set(git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()) == set(paths), 'commit paths differ')
    # Ordinary push rejects a concurrent update. Never force, merge, or change main.
    # The existing ephemeral workflow token is available only to this push process.
    # No credential helper, URL credential, or persistent Git configuration is written.
    push_environment = dict(os.environ)
    push_environment.update({
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
        'GIT_CONFIG_VALUE_0': 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode(),
        'GIT_TERMINAL_PROMPT': '0',
    })
    subprocess.run(['git', '-C', str(root), 'push', 'origin', 'HEAD:refs/heads/' + branch], check=True, env=push_environment)
    require(git(root, 'ls-remote', 'origin', 'refs/heads/' + branch).split()[0] == commit, 'remote publication not verified')
    print(json.dumps({'runtime_commit': commit, 'parent': expected_head, 'changed_paths': len(paths),
                      'next_step': 'Connector-authored receipt commit triggers ordinary CI; no build claimed.'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    publish(args.root.resolve(), args.expected_head)
