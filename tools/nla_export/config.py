"""Portable contract for the EXPORT_MANIFEST text stored in the canonical BLEND."""
import math
import re

SCHEMA = 'rust-duty-weapon-nla/v1'
SOURCE = 'assets/authoring/weapon_animations.blend'


def validate(manifest):
    if manifest.get('schema') != SCHEMA or not manifest.get('clips'):
        raise ValueError('EXPORT_MANIFEST needs schema ' + SCHEMA + ' and nonempty clips')
    seen = set()
    for clip in manifest['clips']:
        key = clip.get('id', '')
        if not re.fullmatch(r'[a-z0-9_]+', key) or key in seen:
            raise ValueError('Clip IDs must be unique lowercase filename-safe identifiers: ' + key)
        seen.add(key)
        for field in ('scene', 'rig', 'track_name'):
            if not isinstance(clip.get(field), str) or not clip[field]:
                raise ValueError(key + ': missing ' + field)
        if not clip['track_name'].startswith('EXPORT::'):
            raise ValueError(key + ': only explicitly designated EXPORT:: tracks may be exported')
        for field in ('frame_start', 'frame_end', 'fps'):
            if (type(clip.get(field)) not in (int, float) or not math.isfinite(clip[field])
                    or int(clip[field]) != clip[field]):
                raise ValueError(key + ': ' + field + ' must be an integer')
        if clip['frame_end'] < clip['frame_start'] or clip['fps'] <= 0:
            raise ValueError(key + ': invalid duration or FPS')
        base = clip.get('fps_base', 1.0)
        if not isinstance(base, (int, float)) or not math.isfinite(base) or base <= 0:
            raise ValueError(key + ': invalid fps_base')
        step = clip.get('bake_step', 0.125)
        if not isinstance(step, (int, float)) or not math.isfinite(step) or not 0.01 <= step <= 1.0:
            raise ValueError(key + ': bake_step must be between 0.01 and 1 native frame')
        if clip.get('camera_track_name') and not clip.get('camera'):
            raise ValueError(key + ': a camera track requires a camera object')
        if 'objects' in clip and (not clip['objects'] or len(set(clip['objects'])) != len(clip['objects'])):
            raise ValueError(key + ': export objects must be nonempty and unique')
    return manifest
