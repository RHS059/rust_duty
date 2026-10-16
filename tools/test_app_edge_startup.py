"""Static integration regressions only. Rust parser tests remain pending Cargo."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).absolute().parents[1]
NEW = HERE
CONTRACTS = json.loads((HERE / 'tools/combined_source_contracts.json').read_text(encoding='utf-8'))
OLD_CALL = '''    let (level_selection, city) =
        crate::level_menu::choose(&args, &authored_executable, &mut game_update).await?;
'''
NEW_CALL = '''    let (level_selection, city) = crate::level_menu::choose(
        &args,
        &authored_executable,
        &mut game_update,
        app_edge_options.as_ref(),
    )
    .await?;
'''
OLD_DECISION = '''    let scripted = !menu_capture
        && args
            .iter()
            .any(|a| a.starts_with("--capture") || a == "--demo");
'''
NEW_DECISION = '''    let scripted = vector_range::high_app_edge_input::starts_without_level_menu(args, app_edge);
'''
SIGNATURE = '    app_edge: Option<&vector_range::high_app_edge_input::Options>,\n'
HELPER = '''pub fn starts_without_level_menu(args: &[String], app_edge: Option<&Options>) -> bool {
    if app_edge.is_some() {
        return true;
    }
    let menu_capture = args.iter().any(|a| a == "--capture-level-menu");
    !menu_capture
        && args
            .iter()
            .any(|a| a.starts_with("--capture") || a == "--demo")
}
'''


def read(root, name):
    return (root / 'src' / (name + '.rs')).read_text(encoding='utf-8')


def check_startup(app, menu, library):
    assert app.count(NEW_CALL) == 1, 'menu must receive existing parsed options'
    assert app.index('Options::parse(&args)?') < app.index(NEW_CALL)
    assert app.index(NEW_CALL) < app.index('crate::high_app_edge_capture::Capture::open')
    assert menu.count(SIGNATURE) == 1
    assert menu.count(NEW_DECISION) == 1, 'production menu must consume shared typed predicate'
    assert menu.index(NEW_DECISION) < menu.index('return load(selected, executable);') < menu.index('let mut input = FocusInput::new();')
    assert library.count(HELPER) == 1, 'only validated fixture extends the old menu route'


class StartupSourceTests(unittest.TestCase):
    def test_production_startup_wiring_and_original_repro_reversal(self):
        check_startup(*(read(NEW, x) for x in ('app', 'level_menu', 'high_app_edge_input')))
        with self.assertRaises(AssertionError):
            check_startup(read(NEW, 'app').replace(NEW_CALL, OLD_CALL), read(NEW, 'level_menu').replace(NEW_DECISION, OLD_DECISION), read(NEW, 'high_app_edge_input').replace(HELPER, ''))

    def test_only_call_argument_and_menu_policy_changed(self):
        app=read(NEW,'app').replace(NEW_CALL,OLD_CALL)
        menu=read(NEW,'level_menu').replace(SIGNATURE,'').replace(NEW_DECISION,OLD_DECISION)
        self.assertEqual(hashlib.sha256(app.encode()).hexdigest(),CONTRACTS['startup_base_app_sha256'])
        self.assertEqual(hashlib.sha256(menu.encode()).hexdigest(),CONTRACTS['startup_base_menu_sha256'])
        library=read(NEW,'high_app_edge_input')
        production=library.split('#[cfg(test)]')[0].replace(HELPER+'\n','').replace('/// Diagnostic setup only: reuse Options::parse(args) from the application entry.\n/// The caller validates all app-edge options before awaiting the level menu;\n/// only that explicit fixture may skip the ordinary confirmation prompt.\n','')
        self.assertEqual(hashlib.sha256(production.encode()).hexdigest(),CONTRACTS['startup_base_input_production_sha256'])
        self.assertEqual(re.findall(r'fn (app_edge_\w+)\(',library),CONTRACTS['startup_rust_test_names'])

    def test_actual_parser_menu_regression_matrix_is_in_existing_rust_test(self):
        new = read(NEW, 'high_app_edge_input')
        test = new.split('fn app_edge_guard_is_opt_in_and_rejects_mixed_modes() {', 1)[1].split('    #[test]', 1)[0]
        for marker in ['Options::parse(a).map(|options| starts_without_level_menu(a, options.as_ref()))', '("pause", Case::Pause)', '("reset", Case::Reset)', '("debug-death", Case::DebugDeath)', 'LevelSelection::from_options(&a, Some("city"))', 'vec!["game"]', 'vec!["game", "--level=range"]', 'vec!["game", "--capture-level-menu", "--demo"]', 'for index in 1..args().len()', 'a.remove(index);', 'assert!(!menu_route(&a).unwrap()', 'assert!(menu_route(&a).is_err()', '"--app-edge-unknown=x"', '"--capture-level-menu"', '"--app-edge-witness=bad"']:
            self.assertIn(marker, test)

    def test_rejects_missing_typed_route_and_blanket_bypass_mutations(self):
        app, menu, lib = (read(NEW, x) for x in ('app', 'level_menu', 'high_app_edge_input'))
        mutations = [(app.replace('        app_edge_options.as_ref(),', '        None,'), menu, lib), (app, menu.replace(NEW_DECISION, OLD_DECISION), lib), (app, menu, lib.replace('if app_edge.is_some() {', 'if args.iter().any(|a| a.starts_with("--app-edge")) {')), (app, menu, lib.replace('    !menu_capture\n', '    true || !menu_capture\n'))]
        for changed in mutations:
            with self.assertRaises(AssertionError):
                check_startup(*changed)

    def test_complete_production_choose_callsite_inventory(self):
        sites = []
        for source in sorted(NEW.rglob('*.rs')):
            relative = source.relative_to(NEW)
            projected = NEW / relative
            text = (projected if projected.exists() else source).read_text(encoding='utf-8')
            for _ in re.finditer(r'\blevel_menu\s*::\s*choose\s*\(', text):
                sites.append(relative.as_posix())
            self.assertNotRegex(text, r'use\s+[^;]*level_menu[^;]*(?:choose|\*)')
        self.assertEqual(sites, ['src/app.rs'])
        self.assertIn(NEW_CALL, read(NEW, 'app'))
        self.assertEqual(read(NEW, 'level_menu').count('pub(crate) async fn choose('), 1)

    def test_exact_reviewed_startup_source_bytes_are_preserved(self):
        for name,expected in CONTRACTS['startup_source_sha256'].items():
            self.assertEqual(hashlib.sha256((NEW/name).read_bytes()).hexdigest(),expected,name)


if __name__ == '__main__':
    unittest.main()
