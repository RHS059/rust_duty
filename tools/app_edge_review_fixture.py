"""Original failed-receipt review fixture, using only invented public bytes.

The failed_rust_receipt function is preserved verbatim from the original review
reproducer. Only its imports are local to this checkout; no external review
workspace, native process, game asset, or source-status admission is required.
"""
import json
from pathlib import Path
import tempfile
from verify_app_edges import verify_config, sha, digest


def failed_rust_receipt():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        def file(name, value):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
            return dict(path=name, bytes=p.stat().st_size, sha256=sha(p))

        source = file('source/example.rs', '// Invented source fixture. Never compiled.\n')
        inventory = [source]
        source_fp = digest(inventory)
        allow = file('allow.json', dict(schema='rust-duty-app-edge-overlay/v1', unapplied=True,
            files=[dict(path='example.rs', sha256=source['sha256'])]))
        binary = file('not-executable.txt', 'Invented binary identity. Never executed.\n')
        receipt = file('high-receipt.json', {'synthetic_only': True})
        asset = file('high.vra', 'Invented asset bytes; not a game asset.\n')
        companions = {suffix: file('high.' + suffix, 'Invented companion.\n') for suffix in ('vrs', 'vrm')}
        manifest = file('manifest.cfg', 'Invented manifest.\n')
        settings = file('settings.cfg', 'Invented settings.\n')
        payload = [receipt, asset, *companions.values(), manifest, settings]
        review = file('review.json', dict(passed=True, app_edge_overlay_sha256=allow['sha256'],
            source_fingerprint=source_fp, package_identity='invented-cpu-fixture',
            high_receipt_sha256=receipt['sha256'], high_asset_sha256=asset['sha256'],
            payload_fingerprint=digest(sorted(payload, key=lambda r: r['path']))))
        failed = file('rust-checks.json', dict(completed=False, exit_code=1,
            rust_tests_passed=False, runtime_checks_passed=False, rust_format_passed=False,
            note='Deliberately failed/nonterminal checks.'))
        log = file('build.log', 'Invented log. No build was performed.\n')
        build = file('build.json', dict(schema='rust-duty-app-edge-build-receipt/v1',
            completed=True, exit_code=0, source_fingerprint=source_fp, binary=binary,
            overlay_allowlist_sha256=allow['sha256'], build_version='SYNTHETIC', build_number=1,
            rust_tests_passed=True, runtime_checks_passed=True,
            command=['cargo','build','--offline','--no-default-features','--features','legacy-macroquad','--bin','vector-range'],
            log=log, rust_checks_receipt=failed))
        config = file('contract.json', dict(schema='rust-duty-app-edge-run-contract/v1', admitted=True,
            root=str(root), recipe='high-onto-app-input-edges/v1', cases=['pause','reset','debug-death'],
            independent_review=review, overlay_allowlist=allow, source_root='source',
            source_files=inventory, source_fingerprint=source_fp, package_identity='invented-cpu-fixture',
            binary=binary, build_receipt=build, build_version='SYNTHETIC', build_number=1,
            high_receipt=receipt, high_asset=asset, high_companions=companions,
            binding=dict(receipt_sha256=receipt['sha256'], asset_sha256=asset['sha256'], return_seconds=.2),
            payload_files=payload, manifest=manifest, settings=settings, runtime='legacy', renderer='gl',
            run_id='invented-cpu-fixture'))
        verify_config(root / config['path'], config['sha256'])
        return dict(admission_accepted=True, checks_receipt_completed=False,
                    checks_receipt_exit_code=1, checks_receipt_all_pass_flags=False)

