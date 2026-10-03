"""Concurrent layer evidence must be distinguished from sequential route coverage."""
import unittest
from verify_gameplay_ads_capture import verify_layer_overlap, verify_walk_episode_clocks

class LayerCaptureTests(unittest.TestCase):
    def rows(self):
        return [dict(sprinting=True, route='ads.exit', walk_weight=.7, run_weight=.3,
                     segment='sprint_interrupt') for _ in range(3)] + [
            dict(sprinting=False, route='ads.entry', walk_weight=.2, run_weight=.5,
                 segment='sprint_to_ads')]
    def test_concurrent_layers_and_early_return_pass(self):
        self.assertEqual(verify_layer_overlap(self.rows()), {
            'simultaneous_run_ads_walk_frames': 3, 'ads_entry_during_run_return_frames': 1})
    def test_serialized_routes_cannot_masquerade_as_overlap(self):
        for key, value in [('walk_weight', 0), ('run_weight', 0), ('route', 'locomotion')]:
            rows=self.rows()
            for row in rows[:3]: row[key]=value
            with self.assertRaisesRegex(ValueError, 'did not overlap'): verify_layer_overlap(rows)
    def test_missing_or_invalid_run_weights_and_delayed_ads_fail(self):
        for mutation in ('missing', 'invalid', 'delayed'):
            rows=self.rows()
            if mutation == 'missing': del rows[0]['run_weight']
            elif mutation == 'invalid': rows[0]['run_weight']=float('nan')
            else: rows[-1]['run_weight']=0
            with self.assertRaises(ValueError): verify_layer_overlap(rows)


class WalkEpisodeClockTests(unittest.TestCase):
    def test_completed_sprint_fade_can_begin_a_new_walk_episode(self):
        verify_walk_episode_clocks([
            dict(simulation_time=3.5,walk_seconds=1.),
            dict(simulation_time=3.6,walk_seconds=1.1),
            dict(simulation_time=3.8,walk_seconds=None),
            dict(simulation_time=4.2,walk_seconds=None),
            dict(simulation_time=4.3,walk_seconds=.1),
            dict(simulation_time=4.4,walk_seconds=.2)])
    def test_mid_fade_reset_or_frozen_phase_fails(self):
        for seconds in (0.,.1):
            with self.assertRaisesRegex(ValueError,'active walk phase'):
                verify_walk_episode_clocks([dict(simulation_time=1.,walk_seconds=.1),
                                           dict(simulation_time=1.1,walk_seconds=seconds)])

    def test_retained_wip_phase_rate_can_slow_without_reset(self):
        verify_walk_episode_clocks([dict(simulation_time=1.,walk_seconds=10.,walk_min_rate=.85),
                                    dict(simulation_time=2.,walk_seconds=10.85,walk_min_rate=.85)])
