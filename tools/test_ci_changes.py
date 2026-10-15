import unittest

from ci_changes import areas
import ci_quality_checks as checks


class CiChangesTests(unittest.TestCase):
    def test_hud_change_runs_game_and_render_but_not_tools_updater_or_authored(self):
        result = areas(['src/hud.rs'])
        self.assertTrue(result['game'] and result['render'] and result['any'])
        self.assertFalse(result['tools'] or result['updater'] or result['authored'] or result['full'])

    def test_docs_only_change_runs_nothing(self):
        result = areas(['docs/CEDAR_JUNCTION.md', 'README.md'])
        self.assertFalse(any(result.values()))

    def test_tools_and_updater_changes_select_their_own_areas(self):
        self.assertTrue(areas(['tools/package_game.py'])['tools'])
        self.assertFalse(areas(['tools/package_game.py'])['game'])
        self.assertTrue(areas(['updater/src/main.rs'])['updater'])
        self.assertFalse(areas(['updater/src/main.rs'])['game'])

    def test_animation_assets_and_viewmodel_code_select_authored_validation(self):
        for path in ('assets/ads/hip.bin', 'src/view_animation.rs', 'src/render/frame.rs',
                     'tools/run_dx12_authored.py'):
            with self.subTest(path=path):
                self.assertTrue(areas([path])['authored'])
        self.assertFalse(areas(['src/hud.rs'])['authored'])

    def test_ci_and_lockfile_edits_or_non_pr_events_run_everything(self):
        for paths in (['.github/workflows/build.yml'], ['Cargo.lock'], ['tools/ci_changes.py']):
            with self.subTest(paths=paths):
                self.assertTrue(all(areas(paths)[name] for name in ('game', 'tools', 'updater', 'render', 'authored', 'full')))
        self.assertTrue(areas([], full=True)['full'])

    def test_lane_selection_keeps_only_requested_lanes(self):
        lanes = checks.pipelines()
        self.assertEqual(set(checks.selected(lanes, 'game')), {'game'})
        self.assertEqual(set(checks.selected(lanes, 'game,python')), {'game', 'python'})
        self.assertEqual(checks.selected(lanes, ''), lanes)


if __name__ == '__main__':
    unittest.main()
