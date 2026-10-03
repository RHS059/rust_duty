import copy
import json
from pathlib import Path
import tempfile
import unittest
from verify_layered_locomotion_capture import verify, compare_rates


class FourDirectionCaptureTests(unittest.TestCase):
    def fixture(self, folder):
        rows=[]
        for index in range(337):
            time=index/30
            if time < .25: segment='ready'
            elif time < 8.25:
                part=int(time-.25)
                segment=('forward','backward','left','right')[part//2]+('_hip' if part%2==0 else '_ads')
            elif time < 8.75: segment='moving_ads'
            elif time < 9.5: segment='rapid_run_interruptions'
            elif time < 10: segment='hip_return'
            else: segment='final_stop'
            direction=next((i for i,name in enumerate(('forward','backward','left','right')) if segment.startswith(name)),0)
            weights=[0,0,0,0]; weights[direction]=1
            row=dict(simulation_time=time,sampling_hz=30,segment=segment,renderer_failed=False,
                     pose_crc32=index,walk_weight=0 if time>=10 or time<.25 else 1,
                     walk_seconds=None if time>=10 or time<.25 else time-.25,
                     run_weight=.5 if segment=='rapid_run_interruptions' else 0,
                     directional_weights=weights,sprinting=segment=='rapid_run_interruptions' and index%2==0,
                     ads_requested='ads' in segment or segment=='rapid_run_interruptions',simulation_ads=1,
                     position=[0,0,0],velocity=[1,0,0],ammo=30,shots=0)
            row['route']='ready' if time>=10 or time<.25 else 'ads.hold' if row['ads_requested'] else 'regular_walk'
            (folder/f'{index:04}.png').write_bytes(b'\x89PNG\r\n\x1a\n'+str(index).encode())
            rows.append(row)
        self.write(folder,rows)
        return rows
    def write(self,folder,rows):
        for index,row in enumerate(rows): (folder/f'{index:04}.png.gameplay.json').write_text(json.dumps(row))
    def test_complete_four_direction_trace_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); self.fixture(folder)
            report,rows=verify(folder)
            self.assertEqual(report['sampling_hz'],30)
            self.assertTrue(report['directional_source_required'])
            self.assertGreater(report['run_ads_walk_overlap_frames'],2)
            self.assertEqual(compare_rates(rows,rows)['common_ticks'],337)
    def test_legacy_loop_cannot_pass_directional_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); rows=self.fixture(folder)
            for row in rows: row['directional_weights']=None
            self.write(folder,rows)
            with self.assertRaisesRegex(ValueError,'declared direction'): verify(folder)
            self.assertFalse(verify(folder,allow_legacy_walk=True)[0]['directional_source_required'])
    def test_pose_or_state_changes_fail_sampling_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=self.fixture(Path(tmp)); changed=copy.deepcopy(rows)
            changed[100]['pose_crc32']+=1
            with self.assertRaisesRegex(ValueError,'changed committed output'): compare_rates(rows,changed)
    def test_renderer_failure_and_missing_native_image_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); rows=self.fixture(folder); rows[0]['renderer_failed']=True; self.write(folder,rows)
            with self.assertRaisesRegex(ValueError,'renderer failed'): verify(folder)
            rows[0]['renderer_failed']=False; self.write(folder,rows); (folder/'0100.png').write_bytes(b'not PNG')
            with self.assertRaisesRegex(ValueError,'native image missing'): verify(folder)
