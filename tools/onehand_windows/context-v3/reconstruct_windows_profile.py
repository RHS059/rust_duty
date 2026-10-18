"""Read-only preparation evidence; never a native resolver or installed-file repair.

Reconstruct in memory only, prove every entire file equals the observed official
Windows archive, then derive raw AST slices. Return hashes, not addon source.
"""
import ast
import hashlib
from pathlib import Path
from candidate_context import file_sha, ordinary, require, strict_json

PREDECESSOR_SHA = '3162a4c5bbc50daa13ec1c84972b0e4b56c2221a909d1aa2c10617c912b0d801'
LINUX_PINS_SHA = '2716811db4b591c14d0044458c608c961aa2dfcad5958f9da6d0b4da8d67dace'
OBSERVATION_SHA = '5ee21d576be9af34c7b4095352aca1b4fde329eca23b79b6f12a189edc9d800a'
OBSERVATION_BYTES = 9422
ARCHIVE_SHA = '933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6'
ARCHIVE_BYTES = 405138423


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_metadata(raw):
    n = raw.count(b'\r\n')
    return {'bytes': len(raw), 'crlf_count': n, 'bare_lf_count': raw.count(b'\n') - n,
            'bare_cr_count': raw.count(b'\r') - n}


def function_slices(raw, names):
    text = raw.decode('utf-8'); lines = text.splitlines(keepends=True); found = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            require(node.name not in found, 'duplicate audited function')
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            source = ''.join(lines[start - 1:node.end_lineno]).encode('utf-8')
            found[node.name] = {'raw_sha256': digest(source), **raw_metadata(source),
                                'start_line': start, 'end_line': node.end_lineno}
    require(set(found) == set(names), 'audited function inventory differs')
    return found


def reconstruct(lf_root, observation_path, predecessor_root):
    predecessor = ordinary(predecessor_root, existing=True)
    require(file_sha(predecessor / 'PINS.json') == PREDECESSOR_SHA, 'predecessor freeze differs')
    freeze = strict_json(predecessor / 'PINS.json')
    for name, expected in freeze.items():
        require(Path(name).name == name and file_sha(predecessor / name) == expected,
                'predecessor source differs: ' + name)
    require(file_sha(predecessor / 'OFFICIAL_ADDON_PINS.json') == LINUX_PINS_SHA, 'Linux profile differs')
    linux = strict_json(predecessor / 'OFFICIAL_ADDON_PINS.json')
    path = ordinary(observation_path, existing=True)
    require(path.stat().st_size == OBSERVATION_BYTES and file_sha(path) == OBSERVATION_SHA,
            'observed report exact bytes differ')
    observed = strict_json(path, 32 * 1024)
    require(observed['schema'] == 'rust-duty-official-addon-observation/v1' and
            observed['status'] == 'observed_diagnostic_only' and observed['diagnostic_only'] is True and
            observed['native_admission'] is False and observed['animation_proof'] is False and
            observed['normalized_hash_acceptance'] is False, 'diagnostic evidence contract differs')
    require(observed['context_pins_sha256'] == PREDECESSOR_SHA and observed['addon_pins_sha256'] == LINUX_PINS_SHA,
            'observation predecessor binding differs')
    require(observed['provenance']['official_archive_sha256'] == ARCHIVE_SHA and
            observed['provenance']['official_archive_bytes'] == ARCHIVE_BYTES,
            'official Windows distribution identity differs')
    rows = observed['files']
    require(type(rows) is list and len(rows) == len(linux['files']) == 10, 'complete ten-file observation required')
    require(len({r['relative_filename'] for r in rows}) == 10 and
            {r['relative_filename'] for r in rows} == set(linux['files']), 'observation file inventory differs')
    root = ordinary(lf_root, existing=True); reconstructed, records = {}, {}; total = 0
    for row in rows:
        name = row['relative_filename']
        require(Path(name).name == name and name.endswith('.py'), 'unsafe observed filename')
        expected_lf = linux['files'][name]; archive, installed = row['archive'], row['installed']
        require(row['archive_equals_installed'] is True and archive == installed, 'archive/installed mismatch')
        require(row['expected_raw_sha256'] == expected_lf and row['archive_raw_matches_expected'] is False and
                row['installed_raw_matches_expected'] is False, 'historical mismatch evidence differs')
        require(archive['bare_cr_count'] == archive['bare_lf_count'] == 0 and archive['crlf_count'] > 0 and
                archive['diagnostic_crlf_to_lf_sha256'] == expected_lf, 'exact CRLF reconstruction premise differs')
        source = ordinary(root / name, existing=True)
        with source.open('rb') as stream:
            lf = stream.read(1024 * 1024 + 1)
        require(len(lf) <= 1024 * 1024 and digest(lf) == expected_lf and b'\r' not in lf,
                'historical exact LF source differs: ' + name)
        windows = lf.replace(b'\n', b'\r\n'); total += len(windows)
        require(total <= 2 * 1024 * 1024, 'reconstruction byte cap exceeded')
        metadata = raw_metadata(windows)
        require(metadata == {k: archive[k] for k in metadata} and digest(windows) == archive['raw_sha256'],
                'reconstructed whole raw archive member differs: ' + name)
        reconstructed[name] = windows
        records[name] = {'historical_lf_sha256': expected_lf, 'historical_lf_bytes': len(lf),
                         'observed_archive_raw_sha256': archive['raw_sha256'], **metadata}
    # All ten entire files have matched before any function pin is derived.
    functions = {name: function_slices(reconstructed[name], names) for name, names in linux['functions'].items()}
    return reconstructed, {'schema': 'rust-duty-windows-addon-reconstruction/v1',
        'predecessor_context_pins_sha256': PREDECESSOR_SHA, 'predecessor_addon_pins_sha256': LINUX_PINS_SHA,
        'observation_sha256': OBSERVATION_SHA, 'observation_bytes': OBSERVATION_BYTES,
        'archive_sha256': ARCHIVE_SHA, 'archive_bytes': ARCHIVE_BYTES,
        'all_ten_whole_raw_files_verified_before_function_derivation': True,
        'reconstructed_total_bytes': total, 'files': records, 'raw_function_slices': functions,
        'installed_files_modified': False, 'normalization_accepted_for_admission': False,
        'addon_imported': False, 'native_execution': False, 'animation_proof': False}


if __name__ == '__main__':
    import argparse, json
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lf-root', type=Path, required=True)
    p.add_argument('--observation', type=Path, required=True)
    p.add_argument('--predecessor', type=Path, required=True)
    args = p.parse_args()
    _, result = reconstruct(args.lf_root, args.observation, args.predecessor)
    print(json.dumps(result, indent=2, sort_keys=True))
