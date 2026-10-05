"""Source-level contracts for GitHub artifact reruns (not a backend emulator)."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ('build', 'blender-assets', 'walk-assets', 'directional-assets', 'ads-assets', 'jump-assets')
STEP = re.compile(r'^      - [^\n]+\n(?:(?: {8,}[^\n]*| *)\n)*', re.M)


def uploads(name):
    text = (ROOT/f'.github/workflows/{name}.yml').read_text()
    result = []
    for match in STEP.finditer(text):
        block = match.group()
        if 'uses: actions/upload-artifact@v4' not in block:
            continue
        def field(key, indent):
            found = re.search(r'^' + ' ' * indent + re.escape(key) + r': (.+)$', block, re.M)
            return found.group(1) if found else None
        path = re.search(r'^          path: (.*\n(?:            .*\n)*)', block, re.M)
        result.append({'name': field('name', 10), 'id': field('id', 8),
                       'if': field('if', 8), 'overwrite': field('overwrite', 10),
                       'path': path.group(1), 'position': match.start()})
    return result


class AttemptArtifactContracts(unittest.TestCase):
    def test_every_alias_requires_prior_successful_immutable_archive(self):
        count = 0
        for workflow in WORKFLOWS:
            previous = {}
            for item in uploads(workflow):
                if item['overwrite'] == 'true':
                    count += 1
                    guard = re.search(r"steps\.([a-z_0-9]+)\.outputs\.artifact-id != ''", item['if'] or '')
                    self.assertIsNotNone(guard, (workflow, item['name']))
                    self.assertIn(f"steps.{guard.group(1)}.outcome == 'success'", item['if'])
                    archive = previous[guard.group(1)]
                    self.assertNotEqual(archive['overwrite'], 'true')
                    self.assertEqual(archive['path'], item['path'])
                    self.assertLess(archive['position'], item['position'])
                    self.assertTrue('github.run_attempt' in archive['name'] or
                                    'steps.identity.outputs.label' in archive['name'])
                else:
                    self.assertIsNotNone(item['id'])
                    previous[item['id']] = item
        self.assertGreater(count, 20)

    def test_attempt_archives_keep_distinct_matrix_and_attempt_names(self):
        for osname in ('Linux', 'Windows'):
            for workflow in WORKFLOWS:
                names = [x['name'] for x in uploads(workflow) if x['overwrite'] != 'true']
                expanded = []
                for attempt in ('1', '2'):
                    expanded += [n.replace('${{ runner.os }}', osname)
                                 .replace('${{ github.run_attempt }}', attempt)
                                 .replace('${{ steps.identity.outputs.label }}', f'0.1.9+build.1000.{attempt}')
                                 for n in names]
                self.assertEqual(len(expanded), len(set(expanded)), workflow)
        names = [x['name'] for x in uploads('build') if x['overwrite'] != 'true']
        matrix = [n.replace('${{ runner.os }}', osname) for osname in ('Linux', 'Windows')
                  for n in names if '${{ runner.os }}' in n]
        self.assertEqual(len(matrix), len(set(matrix)))

    def test_partial_rerun_reuses_only_same_run_validated_generated_aliases(self):
        producers = {x['name'] for workflow in WORKFLOWS for x in uploads(workflow)
                     if x['overwrite'] == 'true' and x['name'].startswith('generated-')}
        count = 0
        for workflow in WORKFLOWS:
            text = (ROOT/f'.github/workflows/{workflow}.yml').read_text()
            for block in STEP.findall(text):
                if 'uses: actions/download-artifact@v4' not in block:
                    continue
                name = re.search(r'^          name: (.+)$', block, re.M).group(1)
                if name.startswith('generated-'):
                    count += 1
                    self.assertIn(name, producers)
                    self.assertNotIn('run-id:', block)  # Default scope is the current run.
                    self.assertNotIn('github-token:', block)
            # Source/hash validation is required before a generated output can be archived.
            if workflow != 'build':
                self.assertIn('tools/check_generated_assets.py', text)
                self.assertLess(text.index('tools/check_generated_assets.py'),
                                min(item['position'] for item in uploads(workflow)
                                    if item['name'].startswith('generated-')))
        self.assertGreaterEqual(count, 5)

    def test_game_aliases_are_gated_by_full_visible_numbered_downloads(self):
        items = uploads('build')
        for platform, suffix in [('windows', 'Windows'), ('linux', 'Linux')]:
            archive = next(x for x in items if x['id'] == f'archive_game_{platform}')
            alias = next(x for x in items if x['name'] == f'vector-range-{platform}-x64')
            self.assertEqual(archive['name'], f'Rust-Duty-${{{{ steps.identity.outputs.label }}}}-{suffix}-x64')
            self.assertIn(f'steps.archive_game_{platform}.outputs.artifact-id', alias['if'])
            self.assertEqual(archive['path'], alias['path'])


if __name__ == '__main__':
    unittest.main()
