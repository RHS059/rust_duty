"""Restore only the exact preserved runtime bytes; never execute archive members."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'download-form':
            require(self.action is None, 'ambiguous download form')
            require(attrs.get('method', '').lower() == 'get', 'unexpected download method')
            self.action = attrs.get('action')
            self.active = True
        if tag == 'input' and self.active and attrs.get('type') == 'hidden':
            name = attrs.get('name')
            require(name not in self.fields, 'duplicate download field')
            self.fields[name] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


def download(row, cache, accept_warning=False):
    target = cache / row['name']
    if target.exists():
        verify_file(target, row)
        return target
    query = urllib.parse.urlencode({'id': row['drive_id'], 'export': 'download'})
    url = 'https://drive.usercontent.google.com/uc?' + query
    for attempt in range(2):
        with urllib.request.urlopen(url, timeout=180) as response:
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                page = response.read(65537)
                require(len(page) <= 65536, 'oversized download warning')
                require(attempt == 0 and accept_warning, 'Drive warning needs explicit owner approval')
                text = page.decode('utf-8')
                require('Google Drive - Virus scan warning' in text, 'unexpected HTML response')
                form = DownloadForm()
                form.feed(text)
                require(form.action == 'https://drive.usercontent.google.com/download', 'unexpected download destination')
                require(set(form.fields) == {'id', 'export', 'confirm', 'uuid'}, 'unexpected download fields')
                require(form.fields['id'] == row['drive_id'] and form.fields['export'] == 'download'
                        and form.fields['confirm'] == 't' and form.fields['uuid'], 'unexpected download identity')
                url = form.action + '?' + urllib.parse.urlencode(form.fields)
                continue
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=cache, delete=False) as stream:
                    temporary = Path(stream.name)
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        require(total <= row['bytes'], 'archive exceeds pinned size')
                        stream.write(chunk)
                verify_file(temporary, row)
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return target
    raise ValueError('archive download did not return bytes')


def verify_file(path, row):
    require(path.is_file() and not path.is_symlink(), 'expected ordinary file')
    require(path.stat().st_size == row['bytes'], 'pinned file size mismatch')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    require(digest == row['sha256'], 'pinned file SHA256 mismatch')


def restore(root, cache, expected_head, accept_warning=False):
    manifest = json.loads((HERE / 'manifest.json').read_text())
    require(git(root, 'rev-parse', 'HEAD') == expected_head, 'checkout differs from trigger')
    require(git(root, 'rev-parse', 'HEAD^') == manifest['base_commit'], 'recovery must directly follow pinned base')
    require(not git(root, 'status', '--porcelain'), 'checkout must be clean')
    remote = git(root, 'ls-remote', 'origin', 'refs/heads/' + manifest['branch']).split()
    require(remote and remote[0] == expected_head, 'remote branch advanced')
    archives = {r['name']: download(r, cache, accept_warning) for r in manifest['archives']}
    destinations = [d['path'] for row in manifest['objects'] for d in row['destinations']]
    require(len(destinations) == 25 and len(set(destinations)) == 25, 'invalid destination set')
    recovered = []
    # Validate all members before modifying any checkout path.
    for row in manifest['objects']:
        with zipfile.ZipFile(archives[row['archive']]) as archive:
            matches = [i for i in archive.infolist() if i.filename == row['member']]
            require(len(matches) == 1 and matches[0].file_size == row['bytes'], 'member inventory mismatch')
            data = archive.read(matches[0])
        require(hashlib.sha256(data).hexdigest() == row['sha256'], 'runtime SHA256 mismatch')
        identity = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(identity == row['git_sha'], 'runtime Git blob mismatch')
        for destination in row['destinations']:
            path = Path(destination['path'])
            require(path.parts[0] == 'assets' and not path.is_absolute() and '..' not in path.parts, 'unsafe runtime path')
            target = root / path
            require(not any(p.is_symlink() for p in [target, *target.parents]), 'symlink destination')
            if destination['operation'] == 'add':
                require(not target.exists(), 'addition unexpectedly exists')
            else:
                require(destination['operation'] == 'replace', 'unknown operation')
                require(git(root, 'hash-object', str(path)) == destination['head_git_sha'], 'replacement baseline changed')
        recovered.append((row, data))
    for row, data in recovered:
        for destination in row['destinations']:
            target = root / destination['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            verify_file(target, row)
    print(json.dumps({'restored_objects': len(recovered), 'destinations': destinations, 'source_head': expected_head}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--accept-approved-drive-warning', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    restore(args.root.resolve(), args.cache.resolve(), args.expected_head, args.accept_approved_drive_warning)


if __name__ == '__main__':
    main()
