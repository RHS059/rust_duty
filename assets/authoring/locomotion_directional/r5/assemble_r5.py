"""Append exactly the independently validated four r5 Actions into frozen r4.

Run Blender 4.3.2 with the frozen r4 source already open, --disable-autoexec.
Only Action datablocks are loaded; no creator geometry, rig or scene is appended.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_integrity import snapshot
from validate_directional_source import extra_snapshot

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe', required=True, type=Path)
    p.add_argument('--longitudinal', required=True, type=Path)
    p.add_argument('--lateral', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--report', required=True, type=Path)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    assert bpy.app.version_string == '4.3.2'
    recipe = json.loads(args.recipe.read_text())
    baseline = Path(bpy.data.filepath)
    assert sha(baseline) == recipe['baseline_sha256']
    assert not args.output.exists(), 'Refuse source overwrite'
    before, structural = snapshot(bpy), extra_snapshot()
    assert len(before['actions']) == 78
    collections = ('objects', 'meshes', 'armatures', 'materials', 'cameras', 'images', 'collections', 'scenes', 'texts')
    inventory = {k: sorted(x.name for x in getattr(bpy.data, k)) for k in collections}
    imported = {}
    for lane in ('longitudinal', 'lateral'):
        path = getattr(args, lane)
        contract = recipe['lanes'][lane]
        assert sha(path) == contract['source_sha256'], lane
        assert contract['independent_preservation_passed'] is True
        names = tuple(contract['actions'])
        assert len(names) == 2 and not any(n in bpy.data.actions for n in names)
        with bpy.data.libraries.load(str(path), link=False) as (source, dest):
            assert set(names).issubset(source.actions)
            dest.actions = list(names)
        assert {a.name for a in dest.actions} == set(names)
        for action in dest.actions:
            assert action.library is None
            # Library append clears this retention flag; restore the creator's value.
            action.use_fake_user = contract['action_metadata'][action.name]['use_fake_user']
            assert action.use_fake_user
        fresh = snapshot(bpy)
        imported_structure = extra_snapshot()
        for name in names:
            assert fresh['actions'][name] == contract['action_fingerprints'][name], name
            assert imported_structure['actions_metadata'][name] == contract['action_metadata'][name], name
            assert imported_structure['actions_extended'][name] == contract['actions_extended'][name], name
            imported[name] = fresh['actions'][name]
    after, new_structural = snapshot(bpy), extra_snapshot()
    assert len(after['actions']) == 82
    assert set(after['actions']) - set(before['actions']) == set(imported)
    assert all(after['actions'][n] == v for n, v in before['actions'].items())
    for k in ('nla', 'drivers', 'packed_images'):
        assert before[k] == after[k], k
    for k, v in structural.items():
        assert (all(new_structural[k].get(n) == value for n, value in v.items())
                if k in ('actions_extended', 'actions_metadata') else new_structural[k] == v), k
    assert inventory == {k: sorted(x.name for x in getattr(bpy.data, k)) for k in collections}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()), compress=True, check_existing=False)
    assert sha(baseline) == recipe['baseline_sha256']
    for lane in ('longitudinal', 'lateral'):
        assert sha(getattr(args, lane)) == recipe['lanes'][lane]['source_sha256']
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        'schema': 'rust-duty-r5-action-only-assembly/v1',
        'blender': bpy.app.version_string,
        'baseline_sha256': recipe['baseline_sha256'],
        'source_sha256': sha(args.output),
        'source_bytes': args.output.stat().st_size,
        'action_count': 82, 'prior_actions_preserved': 78,
        'appended_actions': imported, 'input_sources_unchanged': True,
        'non_action_datablock_inventory_unchanged': True,
        'pre_save_structural_preservation': True,
        'passed': True, 'scope': 'Action-only assembly; fresh reopen/evaluation gates remain separate'
    }, indent=2) + '\n')
    print('ASSEMBLED', args.output, sha(args.output), flush=True)

if __name__ == '__main__':
    main()
