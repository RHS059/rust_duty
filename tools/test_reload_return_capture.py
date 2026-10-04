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
            returning=any(start<=i<start+12 for start in [100,200,250])
            row={'simulation_time':i/60,'route':'reload.return' if returning else 'ready',
                 'return_weight':0.5 if returning else None,'extra_actor_opacity':0.5 if returning else 0,
                 'anchor':[0,0,-.3],'renderer_failed':False,'walk_weight':0.5,'run_weight':0.5,
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
