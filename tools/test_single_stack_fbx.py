import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
import unittest
import single_stack_fbx as s

TAKE='aella_mantle_onehand_r6_camera_reconstructed_v6'
OWNERS=['Arms','hk416_weapon','hk416_magazine','hk416_magazine_outgoing']
def node(kind,props=(),elems=()):return N(id=kind,props=list(props),elems=list(elems))
def named(kind,uuid,name,cls):return node(kind,[uuid,name.encode()+b'\x00\x01'+cls,b''])
def fixture():
    objects=[named(b'AnimationStack',1,TAKE,b'AnimStack'),named(b'AnimationLayer',2,TAKE,b'AnimLayer')]
    objects += [named(b'Model',i+10,name,b'Model') for i,name in enumerate(OWNERS)]
    return node(b'',elems=[node(b'Objects',elems=objects),node(b'Connections',elems=[node(b'C',[b'OO',2,1])])])
def contract():return s.inspect_stack(fixture(),TAKE,OWNERS)
def imported():
    actions=[N(name=(owner+'|'+TAKE)[:63],frame_range=[1.,96.],fcurves=[N()]) for owner in OWNERS]
    owners=[N(name=name,animation_data=N(action=action,nla_tracks=[])) for name,action in zip(OWNERS,actions)]
    cap=s.BindingCapture(contract())
    for owner,action in zip(owners,actions):cap(1,2,owner,action)
    return cap,owners,actions

class StackTest(unittest.TestCase):
    def test_exact_logical_metadata(self):
        c=contract();self.assertEqual(c['logical_stack'],TAKE)
        self.assertEqual(set(c['owner_model_uuids']),set(OWNERS))
    def test_foreign_and_truncated_logical_take_rejected(self):
        for take in ['foreign',TAKE[:-1],'',None]:
            with self.assertRaises(ValueError):s.inspect_stack(fixture(),take,OWNERS)
    def test_multiple_stacks_rejected(self):
        r=fixture();r.elems[0].elems.append(named(b'AnimationStack',3,'foreign',b'AnimStack'))
        with self.assertRaises(ValueError):s.inspect_stack(r,TAKE,OWNERS)
    def test_multiple_layers_rejected(self):
        r=fixture();r.elems[0].elems.append(named(b'AnimationLayer',3,TAKE,b'AnimLayer'))
        with self.assertRaises(ValueError):s.inspect_stack(r,TAKE,OWNERS)
    def test_missing_or_foreign_or_duplicate_layer_link(self):
        for links in [[],[node(b'C',[b'OO',2,999])],[node(b'C',[b'OO',2,1])]*2]:
            r=fixture();r.elems[1].elems=links
            with self.assertRaises(ValueError):s.inspect_stack(r,TAKE,OWNERS)
    def test_missing_or_duplicate_owner_model(self):
        for duplicate in [False,True]:
            r=fixture()
            if duplicate:r.elems[0].elems.append(deepcopy(r.elems[0].elems[-1]))
            else:r.elems[0].elems.pop()
            with self.assertRaises(ValueError):s.inspect_stack(r,TAKE,OWNERS)
    def test_duplicate_required_owner(self):
        with self.assertRaises(ValueError):s.inspect_stack(fixture(),TAKE,OWNERS+OWNERS[:1])
    def test_invalid_named_metadata(self):
        for encoded in [b'wrong',TAKE.encode()+b'\x00\x01Other',b'\xff\x00\x01AnimStack']:
            r=fixture();r.elems[0].elems[0].props[1]=encoded
            with self.assertRaises(ValueError):s.inspect_stack(r,TAKE,OWNERS)
    def test_valid_bound_truncated_action_without_renaming(self):
        cap,owners,actions=imported();names=[a.name for a in actions]
        result=cap.verify(owners,actions,[1.,96.])
        self.assertEqual(result['owners'][OWNERS[-1]]['action_name'],names[-1])
        self.assertEqual([a.name for a in actions],names)
        self.assertEqual(len(names[-1]),63)
        self.assertFalse(result['action_name_matching'])
    def test_observed_identity_not_action_name_selects(self):
        cap,owners,actions=imported();actions[-1].name='Blender-owned display label'
        result=cap.verify(owners,actions,[1.,96.])
        self.assertEqual(result['owners'][OWNERS[-1]]['action_name'],'Blender-owned display label')
    def test_foreign_stack_or_layer_callback(self):
        cap,owners,actions=imported()
        for stack,layer in [(3,2),(1,4)]:
            with self.assertRaises(ValueError):cap(stack,layer,owners[0],actions[0])
    def test_ambiguous_owner_actions(self):
        cap,owners,actions=imported()
        with self.assertRaises(ValueError):cap(1,2,owners[0],actions[1])
    def test_repeated_bone_callbacks_same_owner_allowed(self):
        cap,owners,actions=imported();cap(1,2,owners[0],actions[0]);cap.verify(owners,actions,[1.,96.])
    def test_missing_callback(self):
        cap,owners,actions=imported();del cap.bindings[s.pointer(owners[0])]
        with self.assertRaises(ValueError):cap.verify(owners,actions,[1.,96.])
    def test_swapped_owner_binding_rejected(self):
        cap,owners,actions=imported();owners[0].animation_data.action=actions[1]
        with self.assertRaises(ValueError):cap.verify(owners,actions,[1.,96.])
    def test_shared_and_foreign_actions_rejected(self):
        cap,owners,actions=imported()
        with self.assertRaises(ValueError):cap.verify(owners,actions[:-1],[1.,96.])
        cap.bindings[s.pointer(owners[1])]=(owners[1],actions[0]);owners[1].animation_data.action=actions[0]
        with self.assertRaises(ValueError):cap.verify(owners,actions,[1.,96.])
    def test_bad_clock_and_empty_action_rejected(self):
        for field,value in [('frame_range',[2.,97.]),('frame_range',[1.,float('nan')]),('fcurves',[])]:
            cap,owners,actions=imported();setattr(actions[0],field,value)
            with self.assertRaises(ValueError):cap.verify(owners,actions,[1.,96.])
    def test_nla_and_owner_inventory_rejected(self):
        cap,owners,actions=imported();owners[0].animation_data.nla_tracks=[N()]
        with self.assertRaises(ValueError):cap.verify(owners,actions,[1.,96.])
        cap,owners,actions=imported()
        with self.assertRaises(ValueError):cap.verify(owners[:-1],actions,[1.,96.])
    def test_instrumentation_records_exact_local_binding(self):
        source='def reader(as_uuid, al_uuid, id_data, action):\n    if True:\n        if True:\n            if True:\n'+s.HOOK_MARKER+'\n                return action\n'
        calls=[];space={s.HOOK_NAME:lambda *a:calls.append(a)}
        exec(s.instrument_reader(source),space)
        owner,action=object(),object();self.assertIs(space['reader'](1,2,owner,action),action)
        self.assertEqual(calls,[(1,2,owner,action)])
    def test_changed_or_duplicate_hook_rejected(self):
        for source in ['def f():pass',s.HOOK_MARKER+'\n'+s.HOOK_MARKER]:
            with self.assertRaises(ValueError):s.instrument_reader(source)
    def test_actual_blender_reader_hook_signature(self):
        p=Path('/usr/share/blender/scripts/addons_core/io_scene_fbx/import_fbx.py')
        if not p.exists():self.skipTest('Blender source unavailable')
        source=p.read_text();tree=ast.parse(source)
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='blen_read_animations')
        text='\n'.join(source.splitlines()[func.lineno-1:func.end_lineno])+'\n'
        ast.parse(s.instrument_reader(text))
    def test_importer_keeps_legacy_selection_separate(self):
        source=(Path(__file__).parent/'import_fbx_viewmodel.py').read_text();ast.parse(source)
        self.assertIn('if args.take and binding_capture is None:',source)
        self.assertIn("require(pair is None, 'single-stack mode is separate",source)
        self.assertIn("single_stack_admission = binding_capture.verify(",source)

if __name__=='__main__':unittest.main()
