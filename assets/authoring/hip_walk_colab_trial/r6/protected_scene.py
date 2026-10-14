"""Additional nonmutating default-transform witnesses for the r6 handoff."""
import bpy


def projection_signature(scene):
    c = scene.camera.data
    r = scene.render
    return [c.type, c.sensor_fit, c.lens, c.sensor_width, c.sensor_height,
            c.shift_x, c.shift_y, c.angle_x, c.angle_y,
            r.resolution_x, r.resolution_y, r.resolution_percentage,
            r.pixel_aspect_x, r.pixel_aspect_y]


def object_defaults():
    return {o.name: {'matrix_basis': [list(r) for r in o.matrix_basis],
                     'matrix_world': [list(r) for r in o.matrix_world],
                     'matrix_parent_inverse': [list(r) for r in o.matrix_parent_inverse],
                     'parent': o.parent.name if o.parent else None,
                     'parent_type': o.parent_type, 'parent_bone': o.parent_bone,
                     'rotation_mode': o.rotation_mode,
                     'location': list(o.location), 'rotation_euler': list(o.rotation_euler),
                     'rotation_quaternion': list(o.rotation_quaternion),
                     'rotation_axis_angle': list(o.rotation_axis_angle), 'scale': list(o.scale),
                     'hide_render': o.hide_render, 'hide_viewport': o.hide_viewport}
            for o in bpy.data.objects}
