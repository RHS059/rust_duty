"""Synthetic log/image fixtures exercise the native Jump gate, not gameplay."""
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from verify_jump_capture import verify


class JumpCaptureGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for i in range(1, 391):
            time = i / 60
            phase = 'none'
            hold = False
            grounded = True
            native = 0.
            accepted = max([s for s in (.25, 1.75, 3.25) if s <= time], default=-10.)
            for start in (.25, 1.75, 3.25):
                age = time - start
                if 0 <= age < .625:
                    grounded = False
                    phase = 'takeoff' if age < 11/60 else 'air'
                    hold = age >= 34/60
                    native = age if phase == 'takeoff' else min(age - 11/60, 23/60)
                elif .625 <= age < .625 + 28/60:
                    phase = 'land'
                    native = age - .625
            if time >= 3.4:
                phase = 'none'; hold = False
            row = dict(simulation_time=time, phase=phase, native_seconds=native, accepted_jump_at=accepted,
                       holding_air_endpoint=hold, grounded=grounded,
                       reload_left=max(0, 5.4-time) if time >= 3.4 else 0,
                       visual_ads=1, renderer_failed=False, pose_crc32=i,
                       sampling_hz=60)
            image = self.folder / f'{i:04}.png'
            Image.new('RGB', (1,1), (i % 256, i // 256, 0)).save(image)
            Path(str(image)+'.gameplay.json').write_text(json.dumps(row))

    def test_valid_control_and_real_violations_are_discriminated(self):
        self.assertTrue(verify(self.folder)['passed'])
        selected = self.folder / '0060.png.gameplay.json'
        original = selected.read_text()
        # t=1.0 is an actual landing witness in the synthetic control.
        for key, value in [('renderer_failed', True), ('grounded', False), ('pose_crc32', None), ('native_seconds', 0), ('accepted_jump_at', -10)]:
            row = json.loads(original); row[key] = value
            selected.write_text(json.dumps(row))
            with self.assertRaises(ValueError): verify(self.folder)
        selected.write_text(original)
        (self.folder / '0060.png').unlink()
        with self.assertRaises(FileNotFoundError): verify(self.folder)
