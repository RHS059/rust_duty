import json
from pathlib import Path
import tempfile
import unittest
from verify_reload_return_capture import verify


class ReturnCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        for i in range(380):
            start=next((start for start,end in [(100,112),(200,206),(250,262)] if start<=i<end),None)
            native_start=next((start for start,end in [(10,100),(170,200),(206,250)] if start<=i<end),None)
            weight=(i-start+1)/13 if start is not None else None
            row={'simulation_time':i/60,'route':'reload.return' if start is not None else 'reload.tactical' if native_start is not None else 'ready',
                 'return_weight':weight,'extra_actor_opacity':1-weight if weight is not None else 1 if native_start is not None else 0,
                 'anchor':[0,0,-.3],'renderer_failed':False,'walk_weight':0.5,'run_weight':0.5,
                 'native_reload_seconds':(i-native_start+1)/60 if native_start is not None else None,'native_reload_duration':1.5,
                 'ammo':12,'reserve':90,'shots':0}
            (self.folder/f'{i:04}.png.gameplay.json').write_text(json.dumps(row))
            (self.folder/f'{i:04}.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')

    def test_complete_interrupted_and_restarted_returns_pass(self):
        self.assertEqual(verify(self.folder)['return_episodes'],3)

    def test_return_anchor_snap_is_rejected(self):
        p=self.folder/'0101.png.gameplay.json';r=json.loads(p.read_text());r['anchor'][0]=.1;p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'jumped'):verify(self.folder)

    def test_immediate_actor_disappearance_is_not_a_fade(self):
        for p in self.folder.glob('*.gameplay.json'):
            r=json.loads(p.read_text());r['extra_actor_opacity']=0;p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'magazine'):verify(self.folder)

    def test_ready_return_only_fixture_cannot_claim_completed_cancelled_reload(self):
        for p in self.folder.glob('*.gameplay.json'):
            r=json.loads(p.read_text())
            if r['route']=='reload.tactical':r['route']='ready';r['native_reload_seconds']=None
            p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'preceding active'):verify(self.folder)

    def test_frozen_return_weight_is_rejected(self):
        for p in self.folder.glob('*.gameplay.json'):
            r=json.loads(p.read_text())
            if r['return_weight'] is not None:r['return_weight']=0.5
            p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'froze'):verify(self.folder)
