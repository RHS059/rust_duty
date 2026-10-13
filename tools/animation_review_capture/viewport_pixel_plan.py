"""Blender4.3.2 camera-display plan for fixed HORIZONTAL, zero-shift camera.

This changes only RegionView3D display zoom/offset. It never moves a camera or
resizes image pixels. Source: BKE_camera_params_from_view3d and
BKE_screen_view3d_zoom_to_fac in exact Blender v4.3.2.
"""
import math

def plan_camera_rectangle(region_width,region_height,width=1280,height=720):
    assert region_width>=width+4 and region_height>=height+4,'Not enough native pixels including border guard'
    assert width==1280 and height==720
    left=(region_width-width)//2;bottom=(region_height-height)//2
    factor=width/region_width
    zoom=(math.sqrt(4*factor)-math.sqrt(2))*50
    center_x=left+width/2;center_y=bottom+height/2
    offset_x=(region_width/2-center_x)/(2*factor*region_width)
    offset_y=(region_height/2-center_y)/(2*factor*region_height)
    return dict(region_dimensions=[region_width,region_height],camera_border_region_bottom_left=[left,bottom,left+width,bottom+height],
        target_dimensions=[width,height],view_camera_zoom=zoom,view_camera_offset=[offset_x,offset_y],zoom_factor=factor)

def rectangle_matches(actual,expected,tolerance=0.01):
    return len(actual)==len(expected)==4 and all(abs(a-b)<=tolerance for a,b in zip(actual,expected))
