"""Replace a strict curve interior while preserving outward endpoint handles.

Blender-facing utility. The caller must independently evaluate protected poses.
"""


def splice_curve(action, path, axis, samples, start=8.0, end=85.0, group='One-hand r4'):
    curve = action.fcurves.find(path, index=axis)
    if curve is None:
        raise ValueError(f'Expected inherited curve {path}[{axis}]')
    for modifier in curve.modifiers:
        if not modifier.mute:
            raise ValueError(f'Active curve modifier needs an explicit preservation plan: {path}')
    original_values = {frame: curve.evaluate(frame) for frame in (start,end)}
    boundaries = {}
    for frame in (start,end):
        key = next((k for k in curve.keyframe_points if abs(k.co.x-frame)<1e-6),None)
        if key is None:
            # All inherited r3 allowed curves should already contain these keys.
            # Refuse an unproven de Casteljau/split approximation at boundaries.
            raise ValueError(f'Missing exact inherited boundary key {path}[{axis}]@{frame}')
        boundaries[frame] = {'left':key.handle_left.copy(),'right':key.handle_right.copy(),
                             'interpolation':key.interpolation,'left_type':key.handle_left_type,
                             'right_type':key.handle_right_type,'value':key.co.y}
    for key in list(curve.keyframe_points):
        if start < key.co.x < end:
            curve.keyframe_points.remove(key,fast=True)
    for frame,value in samples:
        if not start < frame < end:
            continue
        key=curve.keyframe_points.insert(frame,value,options={'FAST'})
        key.interpolation='LINEAR'
    # FREE handles prevent an internal edit from changing an external tangent.
    for frame,saved in boundaries.items():
        key=next(k for k in curve.keyframe_points if abs(k.co.x-frame)<1e-6)
        key.handle_left_type='FREE'
        key.handle_right_type='FREE'
        key.handle_left=saved['left']
        key.handle_right=saved['right']
        key.interpolation='LINEAR' if frame==start else saved['interpolation']
    curve.update()
    for frame,value in original_values.items():
        if abs(curve.evaluate(frame)-value)>1e-7:
            raise ValueError(f'Boundary value drift at {path}[{axis}]@{frame}')
    return curve
