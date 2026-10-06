"""Synthetic pixel/process controls only; never evidence of Windows execution."""
import copy
import json
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
import calibrated_sight_contours as contours
import verify_calibrated_presentation as verify
import run_calibrated_presentation as runner

BINDING={'source_commit':'a'*40,'run_id':'123','run_attempt':'1','executable_sha256':'b'*64}


def marker(image,identity,index=0):
    draw=ImageDraw.Draw(image);draw.rectangle((0,0,31,1),fill=(255,0,0,255));draw.rectangle((32,0,63,1),fill=(0,0,255,255))
    payload=struct.pack('<II',index,index^0xffffffff)+bytes.fromhex(identity)
    for i,byte in enumerate(payload):
        for bit in range(8):
            k=i*8+bit;x=k%32*2;y=2+k//32*2;v=255 if byte&(1<<bit) else 0
            draw.rectangle((x,y,x+1,y+1),fill=(v,v,v,255))


def fixture(folder,backend='Dx12',pose='hip',delta=(0,0),wrong=False,ambiguous=False):
    folder.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGBA',(960,540),(36,48,61,255));draw=ImageDraw.Draw(image);color=(100,100,100,255);x,y=delta
    draw.rectangle((380,345,710,539),fill=color)
    if not wrong:
        for offset in ([0,-240] if ambiguous else [0]):
            cx,cy=(625+x+offset,293+y) if pose=='hip' else (480+x+offset,270+y)
            draw.ellipse((cx-24,cy-24,cx+24,cy+24),outline=color,width=4)
            fx,fy=(526+x+offset,280+y) if pose=='hip' else (cx,cy)
            draw.ellipse((fx-5,fy-5,fx+5,fy+5),outline=color,width=2)
            if pose=='ads':draw.rectangle((cx-1,cy+5,cx+1,cy+24),fill=color)
    else:
        draw.line((450,270,510,270),fill=color,width=3);draw.line((480,240,480,320),fill=color,width=3)
    expected=verify.identity(BINDING,backend,pose);marker(image,expected)
    path=folder/(pose+'.png');image.save(path)
    metadata={'capture':'native offscreen viewmodel','requested':'dx12' if backend=='Dx12' else 'gl',
              'backend':backend,'adapter':'Microsoft Basic Render Driver' if backend=='Dx12' else 'llvmpipe (synthetic)',
              'width':960,'height':540,'hfov':76,'ads':int(pose=='ads'),'reload_phase':None,
              'frame_witness':{'schema':verify.witness.SCHEMA,'frame_index':0,'capture_identity':expected}}
    Path(str(path)+'.json').write_text(json.dumps(metadata))
    world=Path(str(path)+'.world.png');Image.new('RGBA',(64,64),(168,194,199,255)).save(world)
    world_metadata={**metadata,'capture':'native window','width':64,'height':64}
    world_metadata.pop('frame_witness');Path(str(world)+'.json').write_text(json.dumps(world_metadata))
    light={'schema':'rust-duty-lighting-capture/v1','yaw_degrees':-90,'pitch_degrees':0,'ambient':.35,'diffuse':.65,
           'simulation_time':0,'world_light':[0,1,0],'view_light':[0,1,0]}
    Path(str(path)+'.lighting.json').write_text(json.dumps(light))
    return path,expected


class CalibratedPresentationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def test_true_zero_and_four_pixel_boundary_pass(self):
        for pose,delta in (('hip',(0,0)),('ads',(4,-4))):
            path,identity=fixture(self.root/pose,pose=pose,delta=delta)
            result=verify.validate_capture(path.parent,'Dx12',pose,identity)
            self.assertTrue(result['within_tolerance'],result)
            self.assertEqual(result['measured_center'],[verify.TARGETS[pose][i]+delta[i] for i in range(2)])

    def test_both_backends_matching_displacement_does_not_waive_absolute_failure(self):
        results=[]
        for backend in ('OpenGl','Dx12'):
            for pose in ('hip','ads'):
                path,identity=fixture(self.root/(backend+pose),backend,pose,(20,0))
                results.append(verify.validate_capture(path.parent,backend,pose,identity))
        summary=verify.paired_results(results)
        self.assertFalse(summary['passed'])
        self.assertTrue(all(row['dx12_minus_gl_px']==[0,0] for row in summary['paired_backend_deltas']))

    def test_stale_witness_rejected_before_detector(self):
        path,_=fixture(self.root/'stale')
        with patch.object(contours,'measure',side_effect=AssertionError('localized too early')):
            with self.assertRaisesRegex(ValueError,'identity differs'):
                verify.validate_capture(path.parent,'Dx12','hip','f'*64)

    def test_wrong_hfov_pose_and_unfrozen_time_rejected(self):
        for label,field,value in (('fov','hfov',90),('pose','ads',1),('clock','simulation_time',1)):
            path,identity=fixture(self.root/label)
            sidecar=Path(str(path)+('.lighting.json' if label=='clock' else '.json'))
            metadata=json.loads(sidecar.read_text());metadata[field]=value;sidecar.write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):verify.validate_capture(path.parent,'Dx12','hip',identity)

    def test_missing_world_sidecar_is_not_a_pass(self):
        path,identity=fixture(self.root/'missing');Path(str(path)+'.world.png.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing or unexpected'):verify.validate_capture(path.parent,'Dx12','hip',identity)

    def test_wrong_feature_and_duplicate_openings_fail_closed(self):
        for label,kwargs in (('wrong',{'wrong':True}),('ambiguous',{'ambiguous':True})):
            path,identity=fixture(self.root/label,pose='ads',**kwargs)
            with self.assertRaisesRegex(ValueError,'absent or ambiguous'):verify.validate_capture(path.parent,'Dx12','ads',identity)

    def test_command_keeps_static_mode_and_unchanged_defaults(self):
        for backend in ('OpenGl','Dx12'):
            for pose in ('hip','ads'):
                cmd=runner.command(Path('game.exe'),Path('weapon.vrm'),Path('settings.cfg'),Path('capture'),backend,pose,'a'*64)
                self.assertIn('--reference-viewport',cmd);self.assertIn('--weapon-asset=weapon.vrm',cmd)
                self.assertIn('--capture-lighting',cmd)
                self.assertFalse(any(arg.startswith(('--viewmodel-fov=','--viewmodel-hip=','--viewmodel-ads=','--viewmodel-hip-ypr=','--viewmodel-ads-ypr=')) for arg in cmd))
                self.assertEqual('--capture-ads' in cmd,pose=='ads')
                self.assertEqual('--force-fallback-adapter' in cmd,backend=='Dx12')
                self.assertFalse(any(arg.startswith(('--animation-manifest','--viewmodel-asset','--arms-asset','--capture-sequence','--procedural-weapon')) for arg in cmd))

    def test_single_frame_receipt_counts_explicit_output_not_directory(self):
        logs=self.root/'logs';logs.mkdir();cmd=['game.exe','--capture'];root=Path('/source')
        (logs/'invocation.json').write_text(json.dumps({'command':cmd,'cwd':str(root)}))
        (logs/'process.json').write_text(json.dumps({'status':'passed','exit_code':0,'png_files':1}))
        (logs/'stdout.log').write_text('');(logs/'stderr.log').write_text('Loaded VRMESH01 weapon: 30 mesh parts\n')
        runner.native_receipt(logs,cmd,root)
        (logs/'process.json').write_text(json.dumps({'status':'failed','exit_code':0,'png_files':1}))
        with self.assertRaisesRegex(ValueError,'complete cleanly'):runner.native_receipt(logs,cmd,root)

    def test_platform_and_existing_evidence_fail_before_execution(self):
        with patch.object(runner.sys,'platform','linux'):
            with self.assertRaisesRegex(ValueError,'requires Windows'):runner.run('game.exe',self.root,self.root,self.root/'evidence')
        with patch.object(runner.sys,'platform','win32'):
            with self.assertRaisesRegex(ValueError,'existing'):runner.run('game.exe',self.root,self.root,self.root)

    def test_source_projection_identity_never_reads_calibration_positions(self):
        before={pose:verify.projected_feature_shapes(pose) for pose in ('hip','ads')}
        with patch.object(verify,'TARGETS',{'hip':(10,20),'ads':(30,40)}):
            after={pose:verify.projected_feature_shapes(pose) for pose in ('hip','ads')}
        self.assertEqual(before,after)
        for shapes in before.values():
            self.assertEqual(shapes['near_surround_candidate']['mesh_index'],27)
            self.assertEqual(shapes['far_opening_candidate']['mesh_index'],29)
            self.assertLess(shapes['near_surround_candidate']['camera_depth_m'],shapes['far_opening_candidate']['camera_depth_m'])

    def test_recorded_source_rims_are_independently_concentric(self):
        import math
        path=Path(__file__).resolve().parent.parent/'docs/static-sight-geometry.json'
        data=json.loads(path.read_text())
        self.assertEqual(data['asset_sha256'],verify.ASSET_SHA256)
        for feature in data['features'].values():
            self.assertEqual(len(feature['independent_rim_fits']),2)
            for face in feature['independent_rim_fits']:
                inner,outer=face['circles']
                self.assertGreater(outer['radius_m'],inner['radius_m'])
                self.assertLess(math.dist(inner['center_source_xy'],outer['center_source_xy']),1e-7)
                for circle in (inner,outer):
                    self.assertEqual(circle['support_vertices'],21)
                    residual=max(abs(math.dist(point,circle['center_source_xy'])-circle['radius_m']) for point in circle['support_source_xy'])
                    self.assertLess(residual,1e-7)

    def test_synthetic_results_cannot_omit_or_duplicate_a_role(self):
        row={'backend':'Dx12','pose':'hip','within_tolerance':True,'measured_center':[526,280]}
        with self.assertRaisesRegex(ValueError,'four distinct'):verify.paired_results([row]*4)


if __name__=='__main__':unittest.main()
