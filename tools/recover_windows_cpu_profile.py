#!/usr/bin/env python3
"""Export one immutable failed-capture ETL without running its executable.

The original capture and its failed shutdown verdict are never rewritten.
Successful exports are diagnostic evidence, not a successful capture or FPS gate.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from run_windows_cpu_profile import (command_log, digest, installed_tools, inventory,
                                     require, require_host, validate_scene_log, write)

RUN_ID = '38194089349'
ARTIFACT_ID = '11723285843'
SOURCE = 'f2eab4d4d3d527d153b08a7a9ae403fb40509b0d'
ARCHIVE_SHA256 = '98eea81efe3266abad6aa676ab6b1f26a2a69f094f8acd6bcc71886bd9327d1e'
# These exact bytes were independently retained in the verified compact artifact.
PINNED_REPORTS = {'asset-producers.json': 'c996e84b05421f0ce9e76ee64c7636d8f7974a080689769147d31e1a47577cfe',
 'assets.json': '541f1df72ea57d785164c8a8da640d7801b99404ba345bee5be22c0f07144ae1',
 'build.json': '1ecffe6478a88980290e9188f42f07cde2d735014d5269037deee7d33ccc7cf1',
 'build.log': '141a6dfc9b1ed2e85de1d193bcf8e77dcf7f23126935eb84703195e95eff979e',
 'capture.json': '70d86b01ac675f35223edfc24e50370a99c73db0a34e2c1f2c2aa85e07e0bcda',
 'game.log': 'a3b4ef9ef59ac5b7104158a8a7765ff450a0736c79851e9fbd1c53e892c01078',
 'materialize.json': 'defc8a9a42505196abbc21d7d8f3feba1280d022cbb6838caeba790b04432e84',
 'source.json': '3abaada1e276e791ed62b44d41e4d662af37c47701d4db7a2489239e1cf3edaa',
 'tools.json': '0afc0856323cee5fa731ae05414b20a52ab537e2218bec866971e63706355879',
 'wpr-help.log': '7ad25a1ca79713f8a58936ef4cb1707a75ee9d4dfb0dd204d97f8861842ce7c4',
 'wpr-start.log': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'wpr-status.log': '247cab367d604db2ec7e6bcd3b56fa68d806c7a99d92be69c2ea514efe3e01d0',
 'wpr-stop.log': '56f7594e4d60953c950db6c9a06253129b7d11f145d55c129ff61fe31f466486',
 'xperf-help.log': 'daf75742e545765d14604bad19e66f9a5085f346b723b32cfc7ff4c3e1866b0c',
 'xperf-stack-help.log': '9fa9ab3dab15fe4860e17b8c613b6599f53a0fe7eb9b833e08a33c16c46c1aee'}


def checked_inputs(folder):
    files = inventory(folder)
    expected = set(PINNED_REPORTS) | {'cpu.etl', 'vector-range.exe', 'vector_range.pdb', 'runtime/settings.cfg'}
    require(set(files) == expected, 'Unexpected or missing retained input')
    for name, sha in PINNED_REPORTS.items():
        require(files[name] == sha, 'Original report changed: ' + name)
    capture = json.loads((folder / 'capture.json').read_text(encoding='utf-8'))
    build = json.loads((folder / 'build.json').read_text(encoding='utf-8'))
    source = json.loads((folder / 'source.json').read_text(encoding='utf-8'))
    require(capture['source_commit'] == build['source_commit'] == source['commit'] == SOURCE,
            'Original source identity mismatch')
    require(capture['passed'] is False and capture['exit_code'] == 1,
            'Original failed capture must remain failed')
    for name, key in [('vector-range.exe', 'exe_sha256'), ('vector_range.pdb', 'pdb_sha256')]:
        require(files[name] == capture[key] == build[key], 'Retained binary mismatch: ' + name)
    require(files['runtime/settings.cfg'] == capture['initial_settings_sha256'], 'Retained settings mismatch')
    require((folder / 'cpu.etl').stat().st_size > 0, 'Missing trace bytes')
    validate_scene_log((folder / 'game.log').read_text(encoding='utf-8'))
    for key in ('pid', 'renderer_window_thread_id'):
        require(type(capture[key]) is int and capture[key] > 0, 'Invalid recorded process/thread')
    return files, capture


def exports(xperf, folder, output, capture):
    symbols = str(folder) + ';srv*' + str(output / 'symbols') + '*https://msdl.microsoft.com/download/symbols'
    env = dict(os.environ, _NT_SYMBOL_PATH=symbols, _NT_SYMCACHE_PATH=str(output / 'symcache'))
    reports = {}
    for action, args in [('profile', ['-detail']), ('process', []), ('tracestats', []),
                         ('stack', ['-butterfly']),
                         ('renderer-stack', ['-butterfly', '-event', 'Profile',
                                             '-pid', str(capture['pid']),
                                             '-tid', str(capture['renderer_window_thread_id'])])]:
        command_log([xperf, '-i', folder / 'cpu.etl', '-symbols', '-o', output / (action + '.txt'),
                     '-a', 'stack' if action == 'renderer-stack' else action, *args], output,
                    output / (action + '-export.log'), env=env, timeout=180)
        reports[action + '.txt'] = digest(output / (action + '.txt'))
    require({name: digest(output / name) for name in reports} == reports,
            'Report changed after its export')
    return reports


def recover(folder, output):
    require_host()
    require(os.environ.get('RECOVERY_RUN_ID') == RUN_ID and
            os.environ.get('RECOVERY_ARTIFACT_ID') == ARTIFACT_ID,
            'Only the fixed original artifact is admitted')
    folder, output = folder.resolve(), output.resolve()
    require(folder != output and folder not in output.parents and output not in folder.parents,
            'Original input and new output must be disjoint')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'rust-duty-cpu-profile-recovery/v1', 'exports_completed': False,
               'original_capture_passed': False, 'original_capture_source': SOURCE,
               'original_run_id': RUN_ID, 'original_artifact_id': ARTIFACT_ID,
               'original_archive_sha256': ARCHIVE_SHA256,
               'archive_digest_verification': 'download-artifact log; independently compare to pinned GitHub digest',
               'recovery_source_commit': os.environ.get('GITHUB_SHA'),
               'top_functions_reviewed': False,
               'scope': 'Read-only exports of saved WARP trace; original shutdown failed; no FPS inference'}
    before = None
    pending_error = None
    try:
        before, capture = checked_inputs(folder)
        receipt.update(input_files_sha256=before, original_error=capture['error'],
                       original_exit_code=capture['exit_code'], original_cleanup_errors=capture['cleanup_errors'],
                       pid=capture['pid'], renderer_window_thread_id=capture['renderer_window_thread_id'])
        xperf = installed_tools()['xperf']
        xperf_hash = digest(xperf)
        receipt['xperf'] = {'path': str(xperf), 'sha256': xperf_hash}
        receipt['reports_sha256'] = exports(xperf, folder, output, capture)
        require(digest(xperf) == xperf_hash, 'Installed exporter changed')
        require(inventory(folder) == before, 'Original artifact changed during export')
        receipt['exports_completed'] = True
    except BaseException as error:
        receipt['error'] = str(error)
        pending_error = error
    finally:
        if before is not None:
            try:
                receipt['original_inputs_unchanged'] = inventory(folder) == before
                require(receipt['original_inputs_unchanged'], 'Original input changed at final recheck')
            except BaseException as error:
                receipt['original_inputs_unchanged'] = False
                receipt['input_recheck_error'] = str(error)
                receipt['exports_completed'] = False
                if pending_error is None:
                    pending_error = error
                    receipt['error'] = str(error)
        write(output / 'recovery.json', receipt)
    if pending_error is not None:
        raise pending_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        recover(args.input, args.output)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
