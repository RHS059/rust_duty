#!/usr/bin/env python3
"""Stage a WIP human-playtest preview of the exact successful DX12 WARP binary.

This creates only a fresh local artifact directory. It never rebuilds a binary,
publishes a release, or changes the updater. Windows/audio/visual acceptance is
not implied by packaging or by the synthetic tests of this helper.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

import build_identity
import package_game
import run_dx12_smoke as smoke
from verify_capture_telemetry import read_record


BUILD_COMMAND = ['cargo', 'build', '--locked', '--release', '--features',
                 'wgpu-runtime', '--bin', 'vector-range']
FEATURES = ['audio', 'legacy-macroquad', 'wgpu-runtime']
LAUNCHER = '@echo off\r\ncd /d "%~dp0"\r\n"%~dp0vector-range.exe" --renderer=dx12 --no-update\r\nexit /b %ERRORLEVEL%\r\n'
INSTRUCTIONS = """Rust Duty DX12 WIP preview

Extract the complete folder, then run PLAYTEST_DX12.cmd for the human DX12
playtest. It requests DX12 with normal adapter selection (no forced WARP) and
disables release-channel updates for this preview launch. Directly opening
vector-range.exe still uses the legacy renderer by default until M4 sign-off.

This exact executable passed the recorded CI DX12 WARP capture smoke before
packaging. That does not establish real-GPU performance, sound playback, native
interaction correctness, visual approval, or M4 cutover acceptance. Report the
actual adapter, machine and observed behavior when reviewing the preview.

Keep ui/theme.css, documentation and all assets alongside the executable.
This is an isolated WIP artifact, not a release-channel update or release build.
See DX12_PREVIEW.json and BUILD_IDENTITY.json for exact source, run, features,
executable hash and smoke evidence identity.
"""


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verified_smoke(root, binary, evidence, context):
    require(evidence.is_dir() and not evidence.is_symlink(), 'missing or symlinked smoke evidence')
    require(not (evidence / 'failure.json').exists(), 'smoke evidence contains a failure')
    records = {}
    for name in ('invocation.json', 'summary.json'):
        path = package_game.regular_file(evidence, name)
        records[name] = read_record(path)
    invocation, summary = records['invocation.json'], records['summary.json']
    source = context['source']
    require(invocation.get('source_commit') == source['commit'], 'smoke source commit mismatch')
    for field in ('run_id', 'run_attempt'):
        require(invocation.get(field) == str(source[field]), f'smoke {field} mismatch')
    require(invocation.get('cwd') == str(root), 'smoke working directory mismatch')
    require(invocation.get('command') == smoke.game_command(binary, evidence / 'captures'),
            'smoke command does not identify this exact binary/capture invocation')
    binary_hash = digest(binary)
    require(invocation.get('executable_sha256') == binary_hash
            and summary.get('executable_sha256') == binary_hash, 'smoke executable hash mismatch')
    require(summary.get('schema') == 'rust-duty-dx12-warp-smoke/v1'
            and summary.get('passed') is True
            and type(summary.get('exit_code')) is int and summary['exit_code'] == 0
            and summary.get('backend') == 'Dx12' and summary.get('frames') == smoke.FRAME_COUNT,
            'missing successful clean-exit DX12 WARP smoke summary')
    # Revalidate the actual evidence, not just a boolean in a copied summary.
    for name in ('stdout.log', 'stderr.log'):
        package_game.regular_file(evidence, name)
    identities = smoke.validate_renderer_log(evidence)
    require(summary.get('renderer_logs') == identities, 'smoke renderer logs changed')
    validated = smoke.validate_captures(evidence / 'captures')
    require(summary.get('adapters') == validated['adapters'], 'smoke adapter summary mismatch')
    return binary_hash


def verified_notices(root):
    inventory_path = package_game.regular_file(root, 'tools/game-dependency-notices.json')
    inventory = read_record(inventory_path)
    notices = package_game.regular_file(root, 'THIRD_PARTY_LICENSES.txt')
    lock = package_game.regular_file(root, 'Cargo.lock')
    require(inventory.get('schema') == 'rust-duty-game-dependency-notices/v1'
            and inventory.get('target') == 'x86_64-pc-windows-msvc'
            and inventory.get('cargo_features') == {'default_enabled': True, 'explicit': ['wgpu-runtime']},
            'game notice inventory has wrong build scope')
    require(inventory.get('cargo_lock_hash_policy') == 'CRLF converted to LF; no other changes',
            'game notice inventory has an unknown Cargo.lock hash policy')
    require(inventory.get('cargo_lock_sha256') == hashlib.sha256(lock.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            'game notice inventory has a stale Cargo.lock')
    require(inventory.get('notice_sha256') == digest(notices)
            and inventory.get('notice_bytes') == notices.stat().st_size, 'game notices differ from verified inventory')
    return {'notice_sha256': inventory['notice_sha256'], 'inventory_sha256': digest(inventory_path),
            'preserved_baseline_caveats': inventory.get('preserved_baseline_caveats', [])}


def stage(root, binary, evidence, output, env=None):
    env = os.environ if env is None else env
    root, output = Path(root).resolve(), Path(output).absolute()
    evidence = Path(evidence).absolute()
    require(not output.exists() and not output.is_symlink(), 'refusing existing preview output')
    require(output != root and output not in root.parents, 'preview output must not contain source')
    binary = package_game.regular_file(root, binary)
    require(binary.name == 'vector-range.exe', 'preview requires the Windows game executable')
    with package_game.regular_file(root, 'Cargo.toml').open('rb') as source:
        features = tomllib.load(source)['features']
    require(set(features.get('default', [])) == {'audio', 'legacy-macroquad'}
            and all(name in features for name in FEATURES), 'preview build feature contract changed')
    context = build_identity.context(env)
    binary_hash = verified_smoke(root, binary, evidence, context)
    notice_provenance = verified_notices(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stage-dx12-preview-', dir=output.parent) as temporary:
        destination = Path(temporary) / 'preview'
        package_game.stage(root, binary.relative_to(root).as_posix(), destination,
                           require_generated=True)
        staged_binary = destination / binary.name
        require(digest(staged_binary) == binary_hash and digest(binary) == binary_hash,
                'preview executable differs from the tested binary')
        require(digest(destination / 'THIRD_PARTY_LICENSES.txt') == notice_provenance['notice_sha256'],
                'preview notices differ from verified source')
        identity = build_identity.stamp(destination, 'windows', env)
        require(identity['executable']['sha256'] == binary_hash, 'preview identity hash mismatch')
        source = context['source']
        provenance = {
            'schema': 'rust-duty-dx12-wip-preview/v1', 'status': 'WIP preview; M4 approval pending',
            'source': source, 'display_version': context['display_version'],
            'cargo_build_command': BUILD_COMMAND, 'enabled_features': FEATURES,
            'dx12_shader_compiler': 'Fxc',
            'game_dependency_notices': notice_provenance,
            'executable_sha256': binary_hash, 'default_renderer': 'legacy',
            'human_launch': ['vector-range.exe', '--renderer=dx12', '--no-update'],
            'smoke': {'backend': 'Dx12', 'adapter': smoke.WARP_ADAPTER,
                      'frames': smoke.FRAME_COUNT,
                      'evidence_artifact': f"dx12-warp-smoke-attempt-{source['run_attempt']}",
                      'run_url': source['run_url'],
                      'invocation_sha256': digest(evidence / 'invocation.json'),
                      'summary_sha256': digest(evidence / 'summary.json')},
        }
        (destination / 'DX12_PREVIEW.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
        (destination / 'PLAYTEST_DX12.cmd').write_bytes(LAUNCHER.encode('utf-8'))
        (destination / 'DX12_PREVIEW_README.txt').write_text(INSTRUCTIONS, encoding='utf-8')
        destination.rename(output)
    return {'output': str(output), 'executable_sha256': binary_hash,
            'artifact_name': f"Rust-Duty-{context['display_version']}-DX12-Preview-Windows-x64"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--binary', default='target/release/vector-range.exe')
    parser.add_argument('--smoke-evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = stage(args.root, args.binary, args.smoke_evidence, args.output)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f'DX12 preview staging failed: {error}\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
