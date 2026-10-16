"""Source-only synthetic tests. No private geometry or captured image fixtures."""
import copy
import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw
import verify_prone_gameplay_capture as v
import verify_capture_frame_witness as witness


def frame(index, hz=60):
    t=index/hz
    start=.55 if .55+v.TOLERANCE<t<=1.85+v.TOLERANCE else (2.7 if 2.7+v.TOLERANCE<t<=3.2+v.TOLERANCE else None)
    ret=1.85 if 1.85+v.TOLERANCE<t<2.05-v.TOLERANCE else (3.2 if 3.2+v.TOLERANCE<t<3.4-v.TOLERANCE else None)
    q=None; source=None; outgoing=None; route='ready'; weight=1.
    if start is not None:
        seconds=min(t-start-1/120,v.ENTRY_DURATION)
        source={'seconds':seconds,'frame':1+60*seconds};q=[0.,0.,0.,1.]
        # A synthetic cosmetic camera tilt, never derived from authored geometry.
        if .9<t<1.1:q=[math.sin(.02),0.,0.,math.cos(.02)]
        route='prone.entry_hold';weight=0.
    elif ret is not None:
        x=(t-ret)/.2;weight=x*x*(3-2*x);q=[0.,0.,0.,1.]
        outgoing={'began':ret,'duration':.2,'weight':weight,'frozen_source_frame':69. if ret==1.85 else 30.5}
        route='prone.return'
    position=[0.,0.,9. if t<=3.6 else 8.5]
    ads=1. if 3.4<t<=3.8 else 0.
    return {'schema':'rust-duty-prone-gameplay-capture/v1','simulation_time':t,'sampling_hz':hz,
            'binding':{'synthetic':'binding'},'input_only_replay':True,'renderer_failed':False,
            'segment':next(name for s,name in reversed(v.SEGMENTS) if t>=s),
            'camera_forward':v.rotate(q,[0.,0.,-1.]) if q else [0.,0.,-1.],
            'camera_up':v.rotate(q,[0.,1.,0.]) if q else [0.,1.,0.],
            'camera_eye':[position[0],1.,position[2]],'eye_height':1.,'position':position,
            'velocity':[0.,0.,0.],'gameplay_direction':[0.,0.,-1.],
            'grounded':True,'prone':start is not None or 2.7<t<4.1,'crouched':True,
            'ammo':30,'reserve':90,'shots':0,'reload_left':0.,'reload_ready_at':0.,
            'procedural_weight':weight,'simulation_ads':ads,'visual_ads':ads,
            'ads_requested':3.2+v.TOLERANCE<t<=3.8+v.TOLERANCE,
            'source_clock':source,'return':outgoing,'camera_orientation_xyzw':q,'route':route}


class GameplayVerificationTests(unittest.TestCase):
    def check_frame(self,value,index=34,hz=60):
        v.validate_frame(value,index,hz,{'synthetic':'binding'})

    def rejects(self,value,text,index=34):
        with self.assertRaisesRegex(v.VerificationError,text):self.check_frame(value,index)

    def test_complete_synthetic_sequences_and_exact_shared_times(self):
        fast=[frame(i) for i in range(283)];slow=[frame(i,30) for i in range(142)]
        for hz,frames in [(60,fast),(30,slow)]:
            for i,row in enumerate(frames):self.check_frame(row,i,hz)
            self.assertEqual(v.validate_sequence(frames,hz)['frames'],len(frames))
        self.assertEqual(v.compare_rates(fast,slow)['shared_timestamps'],142)

    def test_seconds_to_frame_uses_actual_accepted_tick(self):
        row=frame(34);self.assertAlmostEqual(row['source_clock']['frame'],1.5)
        self.check_frame(row)
        row['source_clock']['frame']=1.
        self.rejects(row,'seconds/frame mismatch')

    def test_stretched_clock_rejected_even_with_matching_frame(self):
        row=frame(34);row['source_clock']={'seconds':.1,'frame':7.}
        self.rejects(row,'source clock stretched')

    def test_stale_binding_rejected(self):
        row=frame(34);row['binding']={'synthetic':'stale'};self.rejects(row,'loaded binding')

    def test_wrong_capture_timestamp_rejected(self):
        row=frame(34);row['simulation_time']+=.01;self.rejects(row,'capture clock')

    def test_wrong_entry_route_rejected(self):
        row=frame(34);row['route']='ready';self.rejects(row,'source route')

    def test_stale_return_and_autorestart_rejected(self):
        row=frame(230);row['source_clock']={'seconds':0.,'frame':1.};row['route']='prone.entry_hold'
        self.rejects(row,'automatic restart',230)

    def test_return_smoothstep_shared_with_procedural(self):
        row=frame(112);self.check_frame(row,112)
        row['procedural_weight']+=.02;self.rejects(row,'smoothstep/procedural',112)

    def test_stale_return_begin_duration_and_frozen_sample(self):
        for key,value,reason in [('began',1.8,'outgoing clock'),('duration',.4,'outgoing clock'),
                                 ('frozen_source_frame',68.,'frozen source')]:
            row=frame(112);row['return'][key]=value;self.rejects(row,reason,112)

    def test_camera_basis_and_nan_rejected(self):
        row=frame(34);row['camera_forward']=[1.,0.,0.];self.rejects(row,'quaternion/basis')
        row=frame(34);row['velocity'][0]=float('nan');self.rejects(row,'non-finite')

    def test_camera_eye_physics_disagreement_rejected(self):
        row=frame(34);row['camera_eye'][1]+=.1;self.rejects(row,'camera eye/physics')

    def test_endpoint_count_not_fudged(self):
        with self.assertRaisesRegex(v.VerificationError,'capture count'):
            v.validate_sequence([frame(i) for i in range(282)],60)

    def test_rate_route_and_clock_mismatch_rejected(self):
        fast=[frame(i) for i in range(283)];slow=[frame(i,30) for i in range(142)]
        for key,value in [('route','stale'),('simulation_time',.01),('source_clock',{'seconds':0.,'frame':1.})]:
            changed=copy.deepcopy(slow);changed[17][key]=value
            with self.assertRaisesRegex(v.VerificationError,'committed state differs'):
                v.compare_rates(fast,changed)

    def test_stale_input_hash_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'synthetic.txt';p.write_text('original')
            pins={'synthetic.txt':v.sha(p)};v.validate_input_hashes(root,pins)
            p.write_text('changed')
            with self.assertRaisesRegex(v.VerificationError,'input stale'):v.validate_input_hashes(root,pins)
            with self.assertRaisesRegex(v.VerificationError,'unsafe input'):v.validate_input_hashes(root,{'../escape':'0'*64})

    def test_pinned_helpers_unchanged(self):
        here=Path(__file__).parent
        for name,digest in v.HELPER_SHAS.items():self.assertEqual(v.sha(here/name),digest)

    def test_exact_invocation_has_explicit_pair_and_native_window(self):
        cmd=v.expected_command(Path('/root'),Path('/root/out'),60,'1'*64)
        self.assertEqual(cmd,['/root/out/frozen-vector-range','--renderer=gl','--level=range','--capture',
                             '--capture-native-window','--capture-sequence=gameplay-prone','--capture-hz=60',
                             '--animation-manifest=/root/private-runtime-pack-v1/animations.cfg',
                             '--capture-frame-witness='+'1'*64,'--output=/root/out/60'])


class SyntheticWitnessTests(unittest.TestCase):
    def test_wrong_identity_index_and_pixel_rejected(self):
        # A synthetic diagnostic marker, not a screenshot or authored frame.
        identity='1'*64;index=7
        image=Image.new('RGBA',(80,32),(20,40,60,255));draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,31,1),fill=(255,0,0,255));draw.rectangle((32,0,63,1),fill=(0,0,255,255))
        payload=index.to_bytes(4,'little')+(index^0xffffffff).to_bytes(4,'little')+bytes.fromhex(identity)
        for bit in range(320):
            x=(bit%32)*2;y=2+(bit//32)*2;color=255 if payload[bit//8]&(1<<(bit%8)) else 0
            draw.rectangle((x,y,x+1,y+1),fill=(color,color,color,255))
        meta={'frame_witness':{'schema':witness.SCHEMA,'frame_index':index,'capture_identity':identity}}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.png';image.save(path)
            witness.verify(path,meta,index,identity)
            with self.assertRaises(witness.WitnessError):witness.verify(path,meta,index,'2'*64)
            with self.assertRaises(witness.WitnessError):witness.verify(path,meta,index+1,identity)
            stale=copy.deepcopy(meta);stale['frame_witness']['frame_index']=index+1
            with self.assertRaises(witness.WitnessError):witness.verify(path,stale,index+1,identity)
            image.putpixel((0,2),(100,100,100,255));image.save(path)
            with self.assertRaises(witness.WitnessError):witness.verify(path,meta,index,identity)


if __name__=='__main__':unittest.main()
