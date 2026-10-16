"""Exact logical FBX stack admission and observed importer owner bindings.

Action names are evidence only. No truncation guesses, Action renames, candidate
search, or first-Action assignment. An opt-in fresh import records the actual
(stack UUID, layer UUID, owner datablock, Action datablock) used by Blender 4.3.2.
"""
from __future__ import annotations
import math


def require(value, message):
    if not value:
        raise ValueError(message)


def logical_name(node, expected_class):
    require(len(node.props) >= 3 and type(node.props[0]) is int
            and isinstance(node.props[1], bytes), 'malformed FBX named object')
    parts=node.props[1].split(b'\x00\x01')
    require(len(parts)==2 and parts[1]==expected_class and parts[0]
            and b'\x00' not in parts[0], 'malformed FBX logical name/class')
    try:
        return parts[0].decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('invalid UTF-8 FBX logical name') from exc


def inspect_stack(root, expected_take, owners):
    require(isinstance(expected_take,str) and expected_take and '\x00' not in expected_take,
            'single-stack import requires an exact nonempty --take')
    require(owners and len(owners)==len(set(owners))
            and all(isinstance(n,str) and n for n in owners), 'duplicate/invalid required owners')
    objects=[n for n in root.elems if n.id==b'Objects']
    connections=[n for n in root.elems if n.id==b'Connections']
    require(len(objects)==len(connections)==1, 'require one FBX Objects and Connections block')
    stacks=[n for n in objects[0].elems if n.id==b'AnimationStack']
    layers=[n for n in objects[0].elems if n.id==b'AnimationLayer']
    require(len(stacks)==1 and len(layers)==1,
            'single-stack mode requires exactly one logical stack and one layer')
    stack,layer=stacks[0],layers[0]
    require(logical_name(stack,b'AnimStack')==expected_take and stack.props[2]==b'',
            'logical FBX take differs from requested take')
    layer_name=logical_name(layer,b'AnimLayer')
    require(layer.props[2]==b'', 'unsupported animation layer class')
    require(stack.props[0]!=layer.props[0], 'duplicate stack/layer UUID')
    links=[tuple(n.props) for n in connections[0].elems if n.id==b'C']
    layer_links=[p for p in links if len(p)>=3 and p[0]==b'OO' and p[1]==layer.props[0]]
    require(layer_links==[(b'OO',layer.props[0],stack.props[0])],
            'layer must have one unambiguous connection to the exact sole stack')
    models={}
    for node in objects[0].elems:
        if node.id!=b'Model':
            continue
        name=logical_name(node,b'Model')
        if name in owners:
            require(name not in models,'duplicate required FBX owner model')
            models[name]=node.props[0]
    require(set(models)==set(owners),'required FBX owner model missing')
    require(len(set(models.values()))==len(models),'required FBX models share UUID')
    return {'schema':'rust-duty-fbx-single-stack/v1','logical_stack':expected_take,
            'stack_uuid':stack.props[0],'logical_layer':layer_name,'layer_uuid':layer.props[0],
            'owner_model_uuids':models}


def pointer(value):
    return value.as_pointer() if hasattr(value,'as_pointer') else id(value)


class BindingCapture:
    def __init__(self,contract):
        self.contract=contract
        self.bindings={}
    def __call__(self,stack_uuid,layer_uuid,owner,action):
        require(stack_uuid==self.contract['stack_uuid'] and layer_uuid==self.contract['layer_uuid'],
                'importer produced a foreign stack/layer binding')
        require(owner is not None and action is not None,'missing imported owner/Action')
        key=pointer(owner)
        existing=self.bindings.get(key)
        require(existing is None or pointer(existing[1])==pointer(action),
                'one owner received ambiguous imported Actions')
        self.bindings[key]=(owner,action)
    def verify(self,owners,imported_actions,frame_range):
        names=[o.name for o in owners]
        require(len(names)==len(set(names)) and set(names)==set(self.contract['owner_model_uuids']),
                'required imported owner inventory differs')
        require(len(frame_range)==2 and all(math.isfinite(v) for v in frame_range)
                and frame_range[1]>=frame_range[0], 'invalid exact imported frame contract')
        imported={pointer(a) for a in imported_actions}
        records={}; used=set()
        for owner in owners:
            entry=self.bindings.get(pointer(owner))
            require(entry is not None,'no observed sole-stack Action for '+owner.name)
            _,action=entry
            data=getattr(owner,'animation_data',None)
            bound=getattr(data,'action',None)
            require(bound is not None and pointer(bound)==pointer(action),
                    'owner is not bound to its observed sole-stack Action: '+owner.name)
            require(pointer(action) in imported and pointer(action) not in used,
                    'foreign/shared owner Action: '+owner.name)
            require(not getattr(data,'nla_tracks',[]), 'unexpected NLA tracks in fresh sole-stack import')
            values=list(action.frame_range)
            require(values==list(frame_range) and all(math.isfinite(v) for v in values),
                    'owner Action clock differs: '+owner.name)
            require(len(action.fcurves)>0,'owner Action contains no curves: '+owner.name)
            used.add(pointer(action))
            records[owner.name]={'action_name':action.name,'frame_range':values,
                'fcurves':len(action.fcurves),'source_model_uuid':self.contract['owner_model_uuids'][owner.name],
                'bound_to_observed_action':True}
        return {**self.contract,'owners':records,'selection':'observed exact stack/layer/owner binding',
                'action_name_matching':False,'renamed_actions':False}


HOOK_NAME='_rust_duty_single_stack_capture'
HOOK_MARKER='                # And actually populate the action!'


def instrument_reader(source):
    require(source.count(HOOK_MARKER)==1 and HOOK_NAME not in source,
            'Blender animation-reader binding hook signature changed')
    return source.replace(HOOK_MARKER,
        '                '+HOOK_NAME+'(as_uuid, al_uuid, id_data, action)\n'+HOOK_MARKER)
