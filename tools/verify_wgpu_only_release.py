#!/usr/bin/env python3
"""Bind a Windows release executable to its GL-free Cargo/backend configuration.

The binary reports wgpu's compiled backend set without opening a window. Cargo
metadata checks the selected Windows dependency closure and enabled features;
an independent byte scan rejects legacy renderer and GL loader entry points.
This establishes build composition, not gameplay or performance approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tomllib

TARGET = 'x86_64-pc-windows-msvc'
FORBIDDEN_PACKAGES = {'macroquad', 'macroquad_macro', 'miniquad', 'glow', 'glutin', 'khronos-egl'}
FORBIDDEN_FEATURES = {'gles', 'webgl', 'angle', 'glsl'}
BINARY_MARKERS = (
    'macroquad', 'miniquad', 'wgpu_hal::gles', 'wgpu-hal/src/gles',
    'wgpu-hal\\src\\gles', 'opengl32.dll', 'libegl.dll', 'libglesv2.dll',
    'wglCreateContext', 'wglGetProcAddress', 'glXCreateContext',
    'eglGetProcAddress', 'glCreateShader', 'glGenBuffers',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_manifest(manifest):
    features = manifest['features']
    require(set(features['default']) == {'audio', 'wgpu-runtime'},
            'default release must select audio and wgpu-runtime')
    require('legacy-macroquad' not in features, 'removed legacy feature was restored')
    dependencies = manifest['dependencies']
    require(not FORBIDDEN_PACKAGES.intersection(dependencies), 'legacy/GL dependency in manifest')
    wgpu = dependencies['wgpu']
    require(wgpu.get('default-features') is False, 'wgpu defaults enable GLES')
    require(set(wgpu.get('features', [])) == {'std', 'parking_lot', 'dx12', 'metal', 'vulkan', 'wgsl'},
            'wgpu must explicitly select only the supported native backends and WGSL')


def verify_metadata(metadata):
    packages = {package['id']: package for package in metadata['packages']}
    resolve = metadata['resolve']
    nodes = {node['id']: node for node in resolve['nodes']}
    root = resolve['root']
    require(root in nodes and root in packages, 'missing resolved game root')
    require(packages[root]['name'] == 'vector-range', 'metadata root is not the game')
    require({'audio', 'wgpu-runtime'} <= set(nodes[root]['features']),
            'metadata does not describe the shipped feature configuration')
    require('legacy-macroquad' not in nodes[root]['features'], 'resolved legacy feature')
    seen, pending = set(), [root]
    while pending:
        package_id = pending.pop()
        if package_id in seen:
            continue
        require(package_id in nodes and package_id in packages, 'incomplete resolved dependency')
        seen.add(package_id)
        node, package = nodes[package_id], packages[package_id]
        require(package['name'] not in FORBIDDEN_PACKAGES,
                f"forbidden resolved dependency: {package['name']}")
        if package['name'] in {'wgpu', 'wgpu-core', 'wgpu-hal', 'naga'}:
            forbidden = FORBIDDEN_FEATURES.intersection(node['features'])
            require(not forbidden, f"GL features enabled in {package['name']}: {sorted(forbidden)}")
        pending.extend(dependency['pkg'] for dependency in node['deps'])
    require(any(packages[key]['name'] == 'wgpu' for key in seen), 'missing resolved wgpu runtime')
    return sorted(({'name': packages[key]['name'], 'version': packages[key]['version'],
                    'features': sorted(nodes[key]['features'])} for key in seen),
                  key=lambda item: (item['name'], item['version']))


def verify_binary(data):
    require(len(data) >= 64 and data[:2] == b'MZ', 'release is not a Windows PE executable')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    require(offset + 6 <= len(data) and data[offset:offset + 4] == b'PE\0\0',
            'invalid PE header')
    require(struct.unpack_from('<H', data, offset + 4)[0] == 0x8664,
            'release is not Windows x86_64')
    lower = data.lower()
    for marker in BINARY_MARKERS:
        require(marker.lower().encode() not in lower and
                marker.lower().encode('utf-16le') not in lower,
                f'forbidden legacy/GL binary marker: {marker}')
    return {'bytes': len(data), 'sha256': digest(data), 'machine': 'x86_64',
            'checked_markers': list(BINARY_MARKERS)}


def verify_build_info(info):
    require(info.get('schema') == 'rust-duty-renderer-build/v1', 'missing renderer build report')
    require(info.get('wgpu_runtime') is True, 'executable lacks wgpu-runtime')
    require(info.get('debug_assertions') is False, 'executable is not a release build')
    require(set(info.get('native_backends', [])) == {'dx12', 'vulkan'},
            'Windows executable must contain only DX12 and Vulkan backends')
    require(bool(info.get('build_number')) and bool(info.get('build_version')),
            'executable build identity is missing')


def command(argv, root):
    result = subprocess.run(argv, cwd=root, capture_output=True, check=True, timeout=300)
    return result.stdout.decode('utf-8')


def verify(root, executable, output):
    root, executable = root.resolve(), executable.resolve()
    manifest_bytes = (root / 'Cargo.toml').read_bytes()
    verify_manifest(tomllib.loads(manifest_bytes.decode('utf-8')))
    metadata_argv = ['cargo', 'metadata', '--locked', '--format-version=1',
                     '--filter-platform', TARGET, '--features', 'wgpu-runtime']
    metadata = json.loads(command(metadata_argv, root))
    dependencies = verify_metadata(metadata)
    binary_bytes = executable.read_bytes()
    binary = verify_binary(binary_bytes)
    info = json.loads(command([str(executable), '--renderer-build-info'], root))
    verify_build_info(info)
    for args in (['--renderer=gl'], ['--renderer', 'gl']):
        rejected = subprocess.run([str(executable), '--no-update', *args], cwd=root,
                                  capture_output=True, timeout=30)
        require(rejected.returncode == 1 and b'unknown renderer' in rejected.stderr,
                'removed GL selection did not fail before window creation')
    require(executable.read_bytes() == binary_bytes, 'release executable changed during verification')
    report = {
        'schema': 'rust-duty-wgpu-only-release/v1', 'passed': True,
        'source_commit': command(['git', 'rev-parse', 'HEAD'], root).strip(),
        'target': TARGET, 'binary': binary, 'renderer_build_info': info,
        'cargo_manifest_sha256': digest(manifest_bytes),
        'cargo_lock_sha256': digest((root / 'Cargo.lock').read_bytes()),
        'cargo_metadata_command': metadata_argv, 'resolved_dependencies': dependencies,
        'rustc': command(['rustc', '-Vv'], root),
        'scope': 'Compiled Windows dependency/backend composition and rejected GL launch; no gameplay or performance claim.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.root, args.executable, args.output)
    print(f"Verified GL-free release {receipt['binary']['sha256']}")
