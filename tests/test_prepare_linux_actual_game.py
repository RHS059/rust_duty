"""Offline safety/provenance tests. No GPU, download, Blender or Cargo build."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("prepare_cpu", TOOLS / "prepare_linux_actual_game.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cpu-prep-test-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, entries):
        path = self.root / "fixture.tar"
        with tarfile.open(path, "w") as archive:
            for name, kind, data in entries:
                item = tarfile.TarInfo(name)
                if kind == "file":
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
                else:
                    item.type = {"dir": tarfile.DIRTYPE, "symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "fifo": tarfile.FIFOTYPE}[kind]
                    item.linkname = data
                    archive.addfile(item)
        return path

    def test_archive_rejects_traversal_before_writes(self):
        archive = self.archive([("good.txt", "file", b"ok"), ("../escape", "file", b"bad")])
        with self.assertRaises(ValueError):
            p.safe_extract(archive, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_archive_rejects_escaping_link(self):
        archive = self.archive([("x", "symlink", "../../outside")])
        with self.assertRaises(ValueError):
            p.safe_extract(archive, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_archive_rejects_link_parent_and_special_file(self):
        for rows in ([('a', 'symlink', 'real'), ('real', 'dir', ''), ('a/escape', 'file', b'bad')], [('x', 'fifo', '')]):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    p.safe_extract(self.archive(rows), self.root / "out")
                self.assertFalse((self.root / "out").exists())

    def test_archive_internal_alias_chain_and_hardlink(self):
        archive = self.archive([("bin", "dir", ""), ("bin/real", "file", b"payload"),
                                ("bin/alias2", "symlink", "real"), ("bin/alias", "symlink", "alias2"),
                                ("hard", "hardlink", "bin/real")])
        p.safe_extract(archive, self.root / "out")
        self.assertEqual((self.root / "out/bin/alias").read_bytes(), b"payload")
        self.assertEqual((self.root / "out/hard").read_bytes(), b"payload")

    def test_archive_rejects_cycle_and_duplicate(self):
        for rows in ([('a', 'symlink', 'b'), ('b', 'symlink', 'a')], [('a', 'file', b'a'), ('a', 'file', b'b')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                p.safe_extract(self.archive(rows), self.root / "out")

    def test_gpu_inventory_fails_closed(self):
        fake = lambda code, out='', err='': subprocess.CompletedProcess([], code, out, err)
        for value in (fake(0, '0, NVIDIA A100, GPU-123'), fake(1, '', 'driver error')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.gpu_gate(run=lambda *a, **k: value, which=lambda *a, **k: '/usr/bin/nvidia-smi', dev_root=self.root)
        empty = p.gpu_gate(run=lambda *a, **k: fake(0), which=lambda *a, **k: '/usr/bin/nvidia-smi', dev_root=self.root)
        self.assertEqual(empty['status'], 'empty')
        no_device = p.gpu_gate(run=lambda *a, **k: fake(6, err='No devices were found\n'), which=lambda *a, **k: '/usr/bin/nvidia-smi', dev_root=self.root)
        self.assertEqual(no_device['status'], 'empty')
        (self.root / 'nvidia0').touch()
        with self.assertRaises(ValueError):
            p.gpu_gate(which=lambda *a, **k: None, dev_root=self.root)

    def test_gpu_gate_precedes_filesystem_setup(self):
        target = self.root / 'never-created'
        with mock.patch.object(p, 'gpu_gate', side_effect=ValueError('GPU present')), self.assertRaisesRegex(ValueError, 'GPU present'):
            p.main(['--support-commit', 'a' * 40, '--asset-helper-sha256', 'b' * 64, '--runs-root', str(target)])
        self.assertFalse(target.exists())

    def test_environment_drops_credentials_preserves_home(self):
        with mock.patch.dict(os.environ, {'HOME': '/existing/home', 'GH_TOKEN': 'DO_NOT_COPY', 'GITHUB_TOKEN': 'DO_NOT_COPY',
                                         'GIT_CONFIG_COUNT': '2', 'RUSTFLAGS': 'bad', 'PIP_INDEX_URL': 'https://secret.invalid', 'LD_PRELOAD': 'bad'}):
            env = p.sanitized_env(self.root)
        self.assertEqual(env['HOME'], '/existing/home')
        self.assertEqual(env['GIT_CONFIG_GLOBAL'], '/dev/null')
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GIT_CONFIG_COUNT', 'RUSTFLAGS', 'PIP_INDEX_URL', 'LD_PRELOAD'):
            self.assertNotIn(key, env)
        for key in ('TMPDIR', 'CARGO_HOME', 'CARGO_TARGET_DIR', 'NETRC'):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))

    def test_download_pin_and_origin_fail_closed_before_network(self):
        for url, expected in [('https://raw.githubusercontent.com/x', 'bad'), ('https://user:secret@raw.githubusercontent.com/x', 'a' * 64),
                              ('https://private.invalid/x', 'a' * 64), ('https://raw.githubusercontent.com/x?token=secret', 'a' * 64)]:
            with self.subTest(url=url), mock.patch.object(p.urllib.request, 'build_opener') as network, self.assertRaises(ValueError):
                p.download(url, self.root / 'out', expected)
            network.assert_not_called()

    def test_download_hash_mismatch_removes_partial(self):
        class Reply(io.BytesIO):
            status = 200
        opener = mock.Mock()
        opener.open.return_value = Reply(b'wrong input')
        with mock.patch.object(p.urllib.request, 'build_opener', return_value=opener), self.assertRaisesRegex(ValueError, 'SHA-256'):
            p.download('https://raw.githubusercontent.com/public/pinned/input', self.root / 'out', 'a' * 64)
        self.assertFalse((self.root / 'out').exists())

    def lock(self):
        return ('version = 4\n\n[[package]]\nname = "wgpu-hal"\nversion = "30.0.1"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\nchecksum = "' + p.CRATE_SHA + '"\ndependencies = ["wgpu-types"]\n\n[[package]]\nname = "unrelated"\nversion = "1.0.0"\nchecksum = "unchanged"\n').encode()

    def test_cargo_overlay_changes_only_one_lock_package(self):
        manifest = b'[dependencies]\nwgpu = { version = "=30.0.1", optional = true }\n'
        new_manifest, new_lock = p.transform_cargo(manifest, self.lock(), self.root / 'vendor')
        self.assertTrue(new_manifest.startswith(manifest))
        parsed = p.tomllib.loads(new_lock.decode())['package']
        self.assertNotIn('checksum', parsed[0])
        self.assertNotIn('source', parsed[0])
        self.assertEqual(parsed[1], {'name': 'unrelated', 'version': '1.0.0', 'checksum': 'unchanged'})
        for invalid in (manifest + b'[patch.crates-io]\na = "1"\n', manifest.replace(b'30.0.1', b'30.0.2')):
            with self.assertRaises(ValueError):
                p.transform_cargo(invalid, self.lock(), self.root / 'vendor')
        with self.assertRaises(ValueError):
            p.transform_cargo(manifest, self.lock().replace(p.CRATE_SHA.encode(), b'0' * 64), self.root / 'vendor')

    def test_reviewed_files_remain_exact_and_outside_cargo_examples(self):
        self.assertEqual(p.sha(TOOLS / 'linux_actual_game_gl.rs'), '23d86f65054fb1fee335d0b5e2b72615e4cf862e4de836acba249361ee210b78')
        self.assertEqual(p.sha(TOOLS / 'linux_gl43_context.patch'), '1b72e875031273094e756dfa0c1a914dbecb8d8200f3d5547ceed30243144136')
        self.assertFalse((TOOLS.parent / 'examples/linux_actual_game_gl.rs').exists())

    def test_sparse_checkout_covers_every_helper_pin(self):
        spec = importlib.util.spec_from_file_location('asset_helper', TOOLS / 'build_linux_authored_inputs.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        absent = [name for name in helper.PINNED_FILES if not any(name == path or (path.endswith('/') and name.startswith(path)) for path in p.SPARSE_PATHS)]
        self.assertEqual(absent, [])
        self.assertFalse(any('soldier' in name.lower() for name in p.SPARSE_PATHS))

    def test_asset_receipt_rejects_missing_or_unvalidated_group(self):
        value = {'schema': 'rust-duty-public-authored-build/v1', 'status': 'passed', 'production_files_preserved': True,
                 'inputs': {'source_commit': p.SOURCE_COMMIT},
                 'groups': {k: {'validation': 'passed', 'files': {'a.vra': {'sha256': 'a' * 64, 'bytes': 1}}} for k in ('reload', 'walk', 'ads', 'directional', 'jump')}}
        for name in ('ASSET_BUILD_RESULT.json', 'receipt.json'):
            p.save(self.root / name, value)
        self.assertEqual(p.check_asset_result(self.root)['status'], 'passed')
        value['groups']['jump']['validation'] = 'failed'
        for name in ('ASSET_BUILD_RESULT.json', 'receipt.json'):
            p.save(self.root / name, value)
        with self.assertRaises(ValueError):
            p.check_asset_result(self.root)

    def test_new_build_identity_uses_fresh_executable(self):
        (self.root / 'examples').mkdir()
        (self.root / 'examples/linux_actual_game_gl.rs').write_bytes(b'test harness')
        binary = self.root / 'vector-range'
        binary.write_bytes(b'new executable bytes')
        receipt = self.root / 'ACTUAL_GAME_HARNESS_RECEIPT.json'
        p.save(receipt, {'test': 'fresh'})
        identity = p.build_identity(self.root, binary, '0.1.11', 'local.123', '0.1.11+build.local.123', receipt)
        self.assertEqual(identity['executable']['sha256'], p.sha(binary))
        self.assertEqual(identity['source']['commit'], p.SOURCE_COMMIT)
        self.assertEqual(identity['benchmark_entrypoint']['receipt_sha256'], p.sha(receipt))
        with self.assertRaises(ValueError):
            p.build_identity(self.root, binary, '0.1.9', 'local.123', '0.1.9+build.local.123', receipt)

    def test_self_check_dry_run_no_external_work(self):
        with mock.patch.object(p, 'gpu_gate') as gate, mock.patch.object(p, 'prepare') as build, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(p.main(['--dry-run']), 0)
        gate.assert_not_called()
        build.assert_not_called()
        self.assertFalse(json.loads(out.getvalue())['runtime_executed'])

    def test_runner_counts_quiet_nested_cpu_as_progress(self):
        env = p.sanitized_env(self.root)
        runner = p.Runner(self.root, env, inactivity=0.15)
        code = "import subprocess,sys; subprocess.run([sys.executable,'-c','import time; end=time.monotonic()+1.3\\nwhile time.monotonic()<end: pass'], start_new_session=True, check=True)"
        runner.run('nested-cpu', [sys.executable, '-I', '-c', code], timeout=5)
        self.assertEqual(runner.phases[0]['status'], 'passed')

    def test_runner_failure_retains_returncode_and_logs(self):
        runner = p.Runner(self.root, p.sanitized_env(self.root), inactivity=180)
        with self.assertRaises(ValueError):
            runner.run('failure', [sys.executable, '-I', '-c', "print('diagnostic'); raise SystemExit(7)"], timeout=5)
        phase = json.loads((self.root / 'PHASES.json').read_text())[0]
        self.assertEqual(phase['exit_code'], 7)
        self.assertEqual(phase['status'], 'failed')
        self.assertIn('diagnostic', (self.root / phase['log']).read_text())

    def test_runner_timeout_kills_owned_nested_process(self):
        runner = p.Runner(self.root, p.sanitized_env(self.root), inactivity=180)
        code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'],start_new_session=True); print(child.pid,flush=True); time.sleep(300)"
        with self.assertRaises(TimeoutError):
            runner.run('timeout', [sys.executable, '-I', '-c', code], timeout=0.2)
        child = int((self.root / 'logs/timeout.log').read_text().strip())
        stat = Path('/proc') / str(child) / 'stat'
        if stat.exists():
            self.assertEqual(stat.read_text().rsplit(') ', 1)[1].split()[0], 'Z')
        self.assertEqual(runner.phases[0]['status'], 'failed')

    def test_public_release_sparse_omits_unused_authoring_and_keeps_weapon(self):
        sparse = p.selected_sparse_paths('public-release')
        self.assertFalse(any(name.endswith('.blend') or name.startswith('assets/authoring/') for name in sparse))
        self.assertIn('assets/weapons/hk416a5.vrm', sparse)
        self.assertIn('assets/source/reload/source.json', sparse)
        with mock.patch.object(p, 'gpu_gate') as gate, contextlib.redirect_stdout(io.StringIO()) as out:
            p.main(['--dry-run', '--asset-mode', 'public-release'])
        value = json.loads(out.getvalue())
        self.assertFalse(value['asset_helper_sha256_required_for_execution'])
        self.assertEqual(value['fresh_authored_groups'], [])
        gate.assert_not_called()

    def test_default_netrc_blocks_anonymous_git_without_reading_contents(self):
        fake_home = self.root / 'fake-home'
        fake_home.mkdir()
        netrc = fake_home / '.netrc'
        netrc.write_text('never read this file')
        with mock.patch.object(p.Path, 'home', return_value=fake_home), mock.patch.object(p.Path, 'read_text', side_effect=AssertionError('secret read')):
            with self.assertRaisesRegex(ValueError, 'credential-free'):
                p.anonymous_git_preflight()
        netrc.unlink()
        with mock.patch.object(p.Path, 'home', return_value=fake_home):
            p.anonymous_git_preflight()

    def release_zip(self, extra=None):
        path = self.root / 'release.zip'
        with p.zipfile.ZipFile(path, 'w') as zipped:
            for group in p.ASSET_GROUPS:
                zipped.writestr('assets/' + group + '/manifest.json', '{}')
                zipped.writestr('assets/' + group + '/asset.vra', 'release asset')
            zipped.writestr('assets/locomotion/README.md', 'old readme')
            zipped.writestr('vector-range', 'old executable')
            zipped.writestr('ui/theme.css', 'old UI')
            zipped.writestr('assets/animations.cfg', 'old config')
            if extra:
                zipped.writestr(*extra)
        return path

    def test_release_overlay_only_selected_assets_preserves_current_readme(self):
        source = self.root / 'source'
        (source / 'assets/locomotion').mkdir(parents=True)
        (source / 'assets/locomotion/README.md').write_text('current readme')
        (source / 'vector-range').write_text('current executable')
        (source / 'assets/animations.cfg').write_text('current config')
        report = p.release_asset_overlay(self.release_zip(), source)
        self.assertEqual((source / 'assets/locomotion/README.md').read_text(), 'current readme')
        self.assertEqual((source / 'vector-range').read_text(), 'current executable')
        self.assertEqual((source / 'assets/animations.cfg').read_text(), 'current config')
        self.assertFalse((source / 'ui').exists())
        self.assertFalse(report['release_executable_extracted'])
        self.assertEqual(len(report['files_from_public_zip']), 12)

    def test_release_source_bindings_are_independent_and_fail_closed(self):
        source = self.root / 'source'
        canonical = {'source': {'contract': 'source49'}, 'files': {'asset.vra': {'sha256': 'a' * 64}}}
        for group, name in {'walk': 'assets/authoring/locomotion/locomotion.blend', 'ads': 'assets/authoring/ads/ads.blend',
                            'directional': 'assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend',
                            'jump': 'assets/authoring/jump/halcyon_jump.blend'}.items():
            expected = p.JUMP_SHA if group == 'jump' else p.AUTHORING_PINS[name]
            p.save(source / 'assets' / group / 'manifest.json', {'source': {'file': name, 'sha256': expected}})
        reload = {'sha256': p.AUTHORING_PINS['assets/source/reload/current.blend'], 'file': 'current.blend'}
        p.save(source / 'assets/source/reload/source.json', reload)
        p.save(source / 'assets/reload/source.json', reload)
        p.save(source / 'assets/locomotion/manifest.json', canonical)
        self.assertEqual(set(p.verify_release_source_bindings(source, canonical)), set(p.ASSET_GROUPS))
        manifest = source / 'assets/jump/manifest.json'
        value = json.loads(manifest.read_text())
        value['source']['sha256'] = '0' * 64
        p.save(manifest, value)
        with self.assertRaisesRegex(ValueError, 'jump'):
            p.verify_release_source_bindings(source, canonical)

    def test_release_zip_rejects_traversal_and_symlinks_before_overlay(self):
        source = self.root / 'source'
        source.mkdir()
        with self.assertRaises(ValueError):
            p.release_asset_overlay(self.release_zip(('../outside', 'bad')), source)
        self.assertEqual(list(source.iterdir()), [])
        member = p.zipfile.ZipInfo('assets/locomotion/link')
        member.create_system = 3
        member.external_attr = (p.stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            p.release_asset_overlay(self.release_zip((member, '../outside')), source)
        self.assertEqual(list(source.iterdir()), [])

    def test_archive_exports_only_selected_fresh_artifacts(self):
        (self.root / 'package').mkdir()
        (self.root / 'package/vector-range').write_bytes(b'fresh')
        (self.root / 'private-unselected').write_bytes(b'excluded')
        result = p.make_archive(self.root, ['package'], self.root / 'fresh.tar.gz')
        self.assertTrue(result['all_archived_file_hashes_verified'])
        with tarfile.open(self.root / 'fresh.tar.gz') as archive:
            self.assertEqual(archive.getnames(), ['package/vector-range'])


if __name__ == '__main__':
    unittest.main()
