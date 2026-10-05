#!/usr/bin/env python3
"""Append verified game dependency notices without changing existing notices.

Uses the exact Windows audio+legacy+wgpu Cargo resolution and original license
files from cached registry archives whose SHA-256 matches Cargo.lock. No network
downloads, invented attribution, updater-collector changes, or legal certification.
Missing/unverifiable inputs fail before either output is changed.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import tomllib


TARGET = 'x86_64-pc-windows-msvc'
FEATURES = ['wgpu-runtime']
BEGIN = b'\n\n========================================================================\nBEGIN GENERATED WINDOWS GAME DEPENDENCY NOTICES\n'
END = b'\nEND GENERATED WINDOWS GAME DEPENDENCY NOTICES\n'
PREFIXES = ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'COPYRIGHT')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def baseline(contents):
    if BEGIN not in contents:
        require(END not in contents, 'generated notices contain an unmatched end marker')
        return contents
    require(contents.count(BEGIN) == 1 and contents.count(END) == 1 and contents.endswith(END),
            'generated notice block is ambiguous or has trailing edits; preserve/reconcile manually')
    return contents.split(BEGIN, 1)[0]


def selected_packages(metadata):
    packages = {package['id']: package for package in metadata['packages']}
    nodes = {node['id']: node for node in metadata['resolve']['nodes']}
    root = metadata['resolve']['root']
    require(root in packages and root in nodes, 'metadata has no resolved game root')
    pending, seen = [root], set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        require(key in packages and key in nodes, f'incomplete dependency resolution: {key}')
        seen.add(key)
        pending.extend(dependency['pkg'] for dependency in nodes[key]['deps'])
    selected = [packages[key] for key in seen if packages[key].get('source') is not None]
    return packages[root], sorted(selected, key=lambda p: (p['name'], p['version'], p['source'])), nodes


def archive_path(package):
    root = Path(package['manifest_path']).parent
    return root.parent.parent.parent / 'cache' / root.parent.name / f"{package['name']}-{package['version']}.crate"


def original_notices(package, locked, allow_missing=False):
    name, version, source = (package[key] for key in ('name', 'version', 'source'))
    key = (name, version, source)
    require(source == 'registry+https://github.com/rust-lang/crates.io-index',
            f'{name} {version}: unsupported source {source}; original notice provenance needs review')
    require(key in locked and re.fullmatch('[0-9a-f]{64}', locked[key].get('checksum', '')),
            f'{name} {version}: missing exact locked registry checksum')
    root = Path(package['manifest_path']).parent
    path = archive_path(package)
    require(path.is_file(), f'{name} {version}: original cached registry archive missing: {path}')
    archive_bytes = path.read_bytes()
    require(sha(archive_bytes) == locked[key]['checksum'], f'{name} {version}: registry archive checksum mismatch')
    archive_root = f'{name}-{version}/'
    with tarfile.open(path, 'r:gz') as archive:
        members = {}
        for member in archive.getmembers():
            require(member.name.startswith(archive_root), f'{name} {version}: unsafe archive root')
            relative = member.name[len(archive_root):]
            require('..' not in PurePosixPath(relative).parts, f'{name} {version}: unsafe archive path')
            if member.isfile():
                require(relative and not relative.startswith('/') and PurePosixPath(relative).as_posix() == relative,
                        f'{name} {version}: noncanonical archive member path')
                require(relative not in members, f'{name} {version}: duplicate archive member')
                members[relative] = member
        require('Cargo.toml' in members, f'{name} {version}: original package manifest missing')
        require(archive.extractfile(members['Cargo.toml']).read() == (root / 'Cargo.toml').read_bytes(),
                f'{name} {version}: extracted package manifest differs from locked archive')
        names = {path for path in members if PurePosixPath(path).name.upper().startswith(PREFIXES)}
        if package.get('license_file'):
            explicit = Path(package['license_file'])
            try:
                relative = explicit.relative_to(root).as_posix() if explicit.is_absolute() else explicit.as_posix()
            except ValueError as error:
                raise ValueError(f'{name} {version}: license_file is outside original package') from error
            require(relative in members, f'{name} {version}: declared license_file missing: {relative}')
            names.add(relative)
        require(names or allow_missing, f'{name} {version}: original license/notice text missing; manual verification required')
        result = []
        for relative in sorted(names):
            require(members[relative].size <= 4 * 1024**2, f'{name} {version}: oversized license file {relative}')
            raw = archive.extractfile(members[relative]).read()
            require(raw, f'{name} {version}: empty original license file {relative}')
            try:
                raw.decode('utf-8')
            except UnicodeError as error:
                raise ValueError(f'{name} {version}: non-UTF8 license text {relative}; manual verification required') from error
            result.append((relative, raw))
    return result


def supplemental_notices(package, entry, source_root, locked_checksum):
    name, version = package['name'], package['version']
    require(entry['archive_sha256'] == locked_checksum, f'{name} {version}: supplemental archive pin mismatch')
    require(source_root is not None, 'supplemental source directory is required')
    prefix = f'{name}-{version}/'
    records, texts = [], []
    with tarfile.open(archive_path(package), 'r:gz') as archive:
        vcs = json.loads(archive.extractfile(prefix + '.cargo_vcs_info.json').read())
        require(vcs['git']['sha1'] == entry['vcs_commit'], f'{name} {version}: supplemental VCS pin mismatch')
        manifest = archive.extractfile(prefix + 'Cargo.toml.orig').read()
        require(sha(manifest) == entry['published_manifest_sha256'], f'{name} {version}: supplemental package manifest mismatch')
        for record in entry['files']:
            relative = Path(record['file'])
            require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe supplemental license file')
            path = Path(source_root) / relative
            require(not path.is_symlink(), 'supplemental license must not be a symlink')
            raw = path.read_bytes()
            require(len(raw) == record['bytes'] and sha(raw) == record['sha256'], f'{name} {version}: supplemental text checksum mismatch')
            require(raw, f'{name} {version}: empty supplemental text')
            raw.decode('utf-8')
            require(isinstance(record['source_commit'], str) and re.fullmatch('[0-9a-f]{40}', record['source_commit'])
                    and isinstance(record['source_url'], str)
                    and f"/blob/{record['source_commit']}/" in record['source_url']
                    and record['source_url'].startswith('https://github.com/'),
                    f'{name} {version}: supplemental URL must identify immutable original source')
            if 'archive_member' in record:
                original = archive.extractfile(prefix + record['archive_member']).read()
                require(sha(original) == record['archive_source_sha256'], f'{name} {version}: supplemental source member mismatch')
                start, end = record['byte_range']
                require(type(start) is int and type(end) is int and 0 <= start < end <= len(original)
                        and original[start:end] == raw, f'{name} {version}: supplemental notice is not an original byte slice')
            texts.append((f"{record['label']} (original upstream/source text; {record['source_url']})", raw))
            records.append(record)
    return texts, records


def generate(metadata, lock_contents, current_notices, supplements=None, source_root=None):
    base = baseline(current_notices)
    existing = set(re.findall(
        r'^([A-Za-z0-9_-]+) ([0-9]+\.[0-9]+\.[0-9]+[^ \r\n]*)\r?\nDeclared license:',
        base.decode('utf-8'), re.MULTILINE))
    lock = tomllib.loads(lock_contents.decode('utf-8'))
    locked = {(p['name'], p['version'], p.get('source')): p for p in lock['package']}
    root, selected, nodes = selected_packages(metadata)
    root_features = set(nodes[root['id']]['features'])
    require({'audio', 'legacy-macroquad', 'wgpu-runtime'} <= root_features,
            'metadata must select default audio+legacy and explicit wgpu-runtime')
    supplement_map = {}
    if supplements is not None:
        require(supplements.get('schema') == 'rust-duty-game-notice-supplements/v1', 'unsupported notice supplement schema')
        for item in supplements['packages']:
            key = (item['name'], item['version'])
            require(key not in supplement_map, 'duplicate supplemental package')
            supplement_map[key] = item
    records, additions, caveats = [], [], []
    for package in selected:
        name, version, source = (package[key] for key in ('name', 'version', 'source'))
        present = (name, version) in existing
        supplement = supplement_map.get((name, version))
        originals = original_notices(package, locked, allow_missing=supplement is not None)
        extra_sources = []
        if supplement:
            require(supplement['status'] in ('verified-upstream-supplement', 'preserved-baseline-unresolved'),
                    f'{name} {version}: unsupported supplement status')
            extra, extra_sources = supplemental_notices(package, supplement, source_root, locked[(name, version, source)]['checksum'])
            originals += extra
            if supplement['status'] == 'preserved-baseline-unresolved':
                # One named inherited gap is disclosed; this never excuses a new
                # missing license or changes the pre-existing notice wording.
                require((name, version) == ('quad-rand', '0.2.3') and present,
                        'unresolved attribution may only preserve the existing quad-rand0.2.3 baseline')
                caveats.append({'name': name, 'version': version, 'vcs_commit': supplement['vcs_commit'],
                                'issue_url': supplement['issue_url'], 'caveat': supplement['caveat']})
            else:
                require(originals, f'{name} {version}: verified supplement has no original notice text')
        append = not present or bool(extra_sources)
        record = {'name': name, 'version': version, 'source': source,
                  'archive_sha256': locked[(name, version, source)]['checksum'],
                  'license_expression': package.get('license'), 'authors': package.get('authors', []),
                  'repository': package.get('repository'),
                  'source_package_url': f'https://crates.io/crates/{name}/{version}',
                  'enabled_features': sorted(nodes[package['id']]['features']),
                  'notice_location': 'generated additions' if append else 'preserved baseline',
                  'files': [{'path': path, 'bytes': len(raw), 'sha256': sha(raw)} for path, raw in originals],
                  'supplemental_sources': extra_sources}
        if supplement:
            record['supplement_status'] = supplement['status']
            record['supplement_notes'] = supplement.get('notes', [])
        records.append(record)
        if not append:
            continue
        heading = (f'\n{"=" * 72}\n{name} {version}\n'
                   f'Declared license: {package.get("license") or "See original license_file below"}\n'
                   f'Registry/source package: {record["source_package_url"]}\n'
                   f'Locked archive SHA-256: {record["archive_sha256"]}\n'
                   f'Upstream: {package.get("repository") or "Not declared in package metadata"}\n').encode('utf-8')
        additions.append(heading)
        emitted = set()
        for path, raw in originals:
            if sha(raw) in emitted:
                continue
            emitted.add(sha(raw))
            additions.extend([f'\n--- Original packaged file: {path} ---\n'.encode('utf-8'), raw, b'\n'])
    preamble = (f'Exact target: {TARGET}\n'
                'Root selection: default features plus wgpu-runtime (audio and legacy retained).\n'
                'Includes the reachable dependency closure, including build/proc-macro crates, as a conservative superset.\n'
                'Existing notices above are preserved byte-for-byte. Additional texts below are copied from original locked registry archives.\n'
                'Versioned source-package links identify the corresponding source; no dependency source was modified for this collection.\n'
                'This inventory is provenance evidence, not legal certification.\n').encode('utf-8')
    for caveat in caveats:
        preamble += (f"\nInherited attribution caveat: {caveat['name']} {caveat['version']}\n"
                     f"{caveat['caveat']}\nPinned upstream commit: {caveat['vcs_commit']}\n"
                     f"Tracked upstream: {caveat['issue_url']}\n").encode('utf-8')
    output = base + BEGIN + preamble + b''.join(additions) + END
    inventory = {'schema': 'rust-duty-game-dependency-notices/v1', 'target': TARGET,
                 'root_package': {'name': root['name'], 'version': root['version']},
                 'cargo_features': {'default_enabled': True, 'explicit': FEATURES},
                 'resolved_root_features': sorted(root_features),
                 'cargo_lock_sha256': sha(lock_contents.replace(b'\r\n', b'\n')),
                 'cargo_lock_hash_policy': 'CRLF converted to LF; no other changes',
                 'preserved_baseline_sha256': sha(base),
                 'preserved_baseline_bytes': len(base), 'notice_sha256': sha(output),
                 'notice_bytes': len(output), 'preserved_baseline_caveats': caveats,
                 'supplement_manifest_sha256': sha(json.dumps(supplements, sort_keys=True, separators=(',', ':')).encode()) if supplements else None,
                 'packages': records}
    inventory['added_packages'] = sum(p['notice_location'] == 'generated additions' for p in records)
    return output, (json.dumps(inventory, indent=2, sort_keys=True) + '\n').encode('utf-8')


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.notices-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('Cargo.toml'))
    parser.add_argument('--metadata', type=Path, help='optional previously captured metadata for this exact target/features')
    parser.add_argument('--notices', type=Path, default=Path('THIRD_PARTY_LICENSES.txt'))
    parser.add_argument('--inventory', type=Path, default=Path('tools/game-dependency-notices.json'))
    parser.add_argument('--supplements', type=Path, default=Path(__file__).with_name('game-license-sources') / 'manifest.json')
    parser.add_argument('--check', action='store_true', help='verify generated outputs without writing')
    args = parser.parse_args(argv)
    try:
        if args.metadata:
            metadata = json.loads(args.metadata.read_text())
        else:
            metadata = json.loads(subprocess.check_output([
                'cargo', 'metadata', '--manifest-path', str(args.manifest), '--locked', '--offline',
                '--format-version', '1', '--features', ','.join(FEATURES), '--filter-platform', TARGET], text=True))
        supplements = json.loads(args.supplements.read_text()) if args.supplements.is_file() else None
        notices, inventory = generate(metadata, args.manifest.with_name('Cargo.lock').read_bytes(), args.notices.read_bytes(),
                                      supplements, args.supplements.parent)
        if args.check:
            require(args.notices.read_bytes() == notices and args.inventory.read_bytes() == inventory,
                    'generated game dependency notices/inventory are stale')
        else:
            atomic_write(args.notices, notices)
            atomic_write(args.inventory, inventory)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Game license collection failed: {error}\n')
    report = json.loads(inventory)
    print(json.dumps({key: report[key] for key in ('notice_sha256', 'notice_bytes', 'added_packages', 'preserved_baseline_sha256')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
