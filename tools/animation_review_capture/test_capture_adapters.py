import ast
import copy
import hashlib
import json
import math
import struct
import tempfile
import unittest
from unittest import mock
import zlib
from pathlib import Path
if __package__:
    from . import capture_common
    from .capture_common import TAKES,CONTRACTS,HERE,validate_contract,frame_map,png_pixels,primer_review_valid,visible_content_nonempty
    from .viewport_pixel_plan import plan_camera_rectangle,rectangle_matches
else:
    import capture_common
    from capture_common import TAKES,CONTRACTS,HERE,validate_contract,frame_map,png_pixels,primer_review_valid,visible_content_nonempty
    from viewport_pixel_plan import plan_camera_rectangle,rectangle_matches

class Contracts(unittest.TestCase):
    def test_eleven_exact_sources(self):
        self.assertEqual(len(TAKES),11)
        for take in TAKES.values(): validate_contract(take,verify_source=False)
        self.assertEqual(TAKES['entry-r4']['action_count'],111)
        self.assertEqual(TAKES['vault-low-r3']['action_count'],88)
        self.assertEqual(TAKES['mantle-onehand-r3']['action_count'],87)
        self.assertEqual(TAKES['walk-forward-candidate']['action_count'],86)
    def test_source_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(capture_common,'INPUT_ROOT',Path(folder)):
            take=copy.deepcopy(TAKES['entry-r4'])
            path=capture_common.source_path(take);path.parent.mkdir();path.write_bytes(b'original unit fixture, not a BLEND')
            take['source_sha256']=capture_common.sha(path)
            validate_contract(take)
            path.write_bytes(b'tampered unit fixture')
            with self.assertRaisesRegex(AssertionError,'SHA-256 mismatch'):validate_contract(take)
    def test_source_mapping_and_closure(self):
        for take in TAKES.values():
            rows=frame_map(take);start,end=take['reference_unique_half_open']
            self.assertEqual(rows[0]['source_frame'],start)
            self.assertEqual([r['output_pts_ticks'] for r in rows],[i*256 for i in range(len(rows))])
            self.assertEqual([r['source_pts_ticks'] for r in rows],[(start+i)*256 for i in range(len(rows))])
            self.assertEqual(sum(r['include_in_unique_playback'] for r in rows),end-start)
            self.assertEqual(rows[-1]['closure_witness'],take['reference_closure'] is not None)
    def test_r4_cannot_select_r1(self):
        self.assertEqual(TAKES['entry-r4']['action'],'prone_crawl_enter_r4')
        self.assertEqual(TAKES['entry-r4']['frames_inclusive'],[1,69])
    def test_walk_pairs_same_source_and_timing(self):
        for direction in ('forward','backward','left','right'):
            a=TAKES['walk-'+direction+'-baseline'];b=TAKES['walk-'+direction+'-candidate']
            for key in ('source','source_sha256','camera','frames_inclusive','reference_unique_half_open','reference_closure','taa_samples'):
                self.assertEqual(a[key],b[key])
    def test_visual_review_exact_scope(self):
        take=TAKES['vault-low-r3']
        primers=[{'sha256':'a','pixel_sha256':'0','visible_content_nonempty':True},{'sha256':'b','pixel_sha256':'1','visible_content_nonempty':True},{'sha256':'c','pixel_sha256':'1','visible_content_nonempty':True}]
        review=dict(accepted=True,take=take['id'],source_sha256=take['source_sha256'],primer_sha256=['a','b','c'],review_note='Actual pixels inspected')
        self.assertTrue(primer_review_valid(review,take,primers))
        for key,value in [('accepted',False),('source_sha256','wrong'),('take','entry-r4'),('primer_sha256',['b','c']),('review_note',''),('review_note','   '),('review_note',True)]:
            bad=dict(review);bad[key]=value
            self.assertFalse(primer_review_valid(bad,take,primers))
        primers[-1]['pixel_sha256']='2'
        self.assertFalse(primer_review_valid(review,take,primers))
    def test_only_viewport_render_calls_no_save_calls(self):
        tree=ast.parse((HERE/'capture_viewport.py').read_text())
        calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertEqual(calls.count('bpy.ops.render.opengl'),2)
        self.assertFalse(any('save_' in x or x=='bpy.ops.render.render' for x in calls))
        self.assertNotIn('CYCLES',(HERE/'capture_viewport.py').read_text())
    def test_validate_only_has_no_renderer_call(self):
        tree=ast.parse((HERE/'capture_viewport.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_only')
        self.assertNotIn('bpy.ops.render',ast.unparse(function))

class Png(unittest.TestCase):
    def test_uniform_black_and_empty_pixels_rejected(self):
        for rgb in [bytes([0,0,0]),bytes([255,255,255]),bytes([23,45,67])]:
            self.assertFalse(visible_content_nonempty((2,2,3),rgb*4))
        self.assertFalse(visible_content_nonempty((0,0,3),b''))
        self.assertFalse(visible_content_nonempty((2,1,4),bytes([0,0,0,0,23,45,67,0])))
        self.assertTrue(visible_content_nonempty((2,1,3),bytes([0,0,0,23,45,67])))
    def test_stable_hashes_cannot_accept_rejected_pixels(self):
        take=TAKES['vault-low-r3']
        primers=[dict(sha256='a',pixel_sha256='b',visible_content_nonempty=False) for _ in range(3)]
        review=dict(accepted=True,take=take['id'],source_sha256=take['source_sha256'],primer_sha256=['a']*3,review_note='Invalid black approval')
        self.assertFalse(primer_review_valid(review,take,primers))

    def test_all_png_filters(self):
        def chunk(tag,content):return struct.pack('>I',len(content))+tag+content+struct.pack('>I',zlib.crc32(tag+content)&0xffffffff)
        # One RGB row has left, above and upper-left branches exercised.
        pixels=bytes([2,14,90,7,28,160,19,72,240]*2)
        w,h,bpp=3,2,3;stride=w*bpp
        for kind in range(5):
            raw=bytearray();old=bytes(stride)
            for y in range(h):
                row=pixels[y*stride:(y+1)*stride];raw.append(kind)
                for x,v in enumerate(row):
                    a=row[x-bpp] if x>=bpp else 0;b=old[x];c=old[x-bpp] if x>=bpp else 0
                    p=a+b-c;ds=[abs(p-a),abs(p-b),abs(p-c)]
                    prior=[a,b,c][ds.index(min(ds))]
                    predictor=[0,a,b,(a+b)//2,prior][kind]
                    raw.append((v-predictor)&255)
                old=row
            encoded=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'test.png';path.write_bytes(encoded)
                self.assertEqual(png_pixels(path),((w,h,3),pixels))
                damaged=bytearray(encoded);damaged[-1]^=1;path.write_bytes(damaged)
                with self.assertRaises(AssertionError):png_pixels(path)

class ViewportDisplayPlan(unittest.TestCase):
    def test_exact_border_size_and_integer_origin(self):
        for w,h in [(1364,964),(1363,963),(1284,724),(1920,1080)]:
            p=plan_camera_rectangle(w,h)
            factor=(math.sqrt(2)+p['view_camera_zoom']/50)**2/4
            self.assertAlmostEqual(w*factor,1280,places=8)
            x,y=p['view_camera_offset'];cx=w/2-2*x*factor*w;cy=h/2-2*y*factor*h
            self.assertTrue(rectangle_matches([cx-640,cy-360,cx+640,cy+360],p['camera_border_region_bottom_left']))
            self.assertTrue(all(isinstance(v,int) for v in p['camera_border_region_bottom_left']))
    def test_undersized_viewport_rejected(self):
        for w,h in [(1280,720),(1364,700),(1200,900)]:
            with self.assertRaises(AssertionError):plan_camera_rectangle(w,h)

if __name__=='__main__':unittest.main()
