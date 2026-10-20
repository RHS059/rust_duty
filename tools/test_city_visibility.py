"""Authored floor/portal topology must never invent a closed exterior wall."""
import copy
import unittest
from unittest import mock

import city_buildings as buildings
import validate_city


def empty_visibility():
    return {'schema': 'rust-duty-city-visibility/v1', 'complete': False,
            'cells': [], 'portals': [], 'portal_count': 0}


def ignore(*args, **kwargs):
    pass


def full_city(visibility=True):
    records, calls = [], []
    graph = empty_visibility() if visibility else None
    buildings.build(lambda *a, **k: calls.append(('asset', a, k)),
                    lambda *a, **k: calls.append(('box', a, k)), records, visibility=graph)
    return {'buildings': records, 'visibility': graph}, calls


class CityVisibilityTests(unittest.TestCase):
    def test_every_shell_opening_is_recorded_directly_and_all_floors_have_cells(self):
        original = buildings.Building.wall
        calls = []

        def inspect(building, x, y, z, width=4, style='solid', side=False, *, exterior=False):
            before = len(building.visibility['portals'])
            original(building, x, y, z, width, style, side, exterior=exterior)
            new = building.visibility['portals'][before:]
            opening = exterior and style in ('window', 'store', 'door')
            self.assertEqual(len(new), 1 if opening else 0)
            if opening:
                self.assertEqual(new[0]['to'], None)
                self.assertEqual(new[0]['from'], f'{building.tag}:{round((y - buildings.FLOOR_Y) / buildings.STORY)}')
                calls.append(style)
        with mock.patch.object(buildings.Building, 'wall', inspect):
            level, _ = full_city()
        graph = level['visibility']
        self.assertTrue(graph['complete'])
        self.assertEqual(len(graph['cells']), sum(spec[2] for spec in buildings.SPECS))
        self.assertEqual(len(graph['cells']), 41)
        self.assertEqual(len(calls), 592)
        self.assertEqual(calls.count('door'), 32)
        self.assertEqual(calls.count('store'), 48)
        self.assertEqual(calls.count('window'), 512)
        self.assertEqual(graph['portal_count'], 617)
        self.assertEqual(len(graph['portals']), 617)
        for building in level['buildings']:
            self.assertNotIn(f"{building['id']}:{building['stories']}", {cell['id'] for cell in graph['cells']})
        report = validate_city.verify_visibility(level)
        self.assertEqual(report, {'status': 'complete', 'complete': True, 'cells': 41,
                                  'portals': 617, 'exterior_portals': 592, 'stair_portals': 25})

    def test_opening_padding_and_normals_follow_north_and_south_shell_transforms(self):
        for south in (False, True):
            for x, z, side, local_normal in ((2, -8, False, [0, 0, -1]),
                                             (-2, 8, False, [0, 0, 1]),
                                             (-8, 2, True, [-1, 0, 0]),
                                             (8, -2, True, [1, 0, 0])):
                with self.subTest(south=south, x=x, z=z):
                    graph = empty_visibility()
                    building = buildings.Building(ignore, ignore, [], 0, 20, 40, south,
                                                  buildings.SPECS[0], visibility=graph)
                    building.wall(x, buildings.FLOOR_Y, z, style='window', side=side, exterior=True)
                    portal = graph['portals'][0]
                    flip = -1 if south else 1
                    self.assertEqual(portal['normal'], [n * flip for n in local_normal])
                    center = [(a + b) / 2 for a, b in zip(portal['min'], portal['max'])]
                    expected = [20 + flip * x, buildings.FLOOR_Y + .9 + .7, 40 + flip * z]
                    for a, b in zip(center, expected):
                        self.assertAlmostEqual(a, b)
                    dimensions = [b - a for a, b in zip(portal['min'], portal['max'])]
                    for a, b in zip(dimensions, [.02, 1.5, 2.1] if side else [2.1, 1.5, .02]):
                        self.assertAlmostEqual(a, b)

    def test_stair_portals_use_actual_floor_holes_and_roof_has_no_cell(self):
        for south in (False, True):
            graph = empty_visibility()
            building = buildings.Building(ignore, ignore, [], 1, 20, 40, south,
                                          buildings.SPECS[1], visibility=graph)
            building.shell()
            portals = [p for p in graph['portals'] if p['to'] is not None]
            self.assertEqual(len(portals), building.stories - 1)
            for hole, portal in zip(building.meta['floor_holes'], portals):
                self.assertEqual(portal['from'], f"B02:{hole['level'] - 1}")
                self.assertEqual(portal['to'], f"B02:{hole['level']}")
                self.assertEqual(portal['normal'], [0, 1, 0])
                for axis, padding in enumerate((.05, .01, .05)):
                    self.assertAlmostEqual(portal['min'][axis], hole['min'][axis] - padding)
                    self.assertAlmostEqual(portal['max'][axis], hole['max'][axis] + padding)
            self.assertNotIn('B02:3', {cell['id'] for cell in graph['cells']})

    def test_topology_does_not_change_geometry_colliders_or_original_building_records(self):
        original, original_calls = full_city(visibility=False)
        current, current_calls = full_city(visibility=True)
        self.assertEqual(original_calls, current_calls)
        self.assertEqual(original['buildings'], current['buildings'])

    def test_unrecognized_shell_mapping_never_claims_complete_topology(self):
        original = buildings.Building.shell

        def unexpected_wall(building):
            original(building)
            building.wall(0, buildings.FLOOR_Y, 0, style='window', exterior=True)
        with mock.patch.object(buildings.Building, 'shell', unexpected_wall):
            level, _ = full_city()
        self.assertFalse(level['visibility']['complete'])
        self.assertEqual(validate_city.verify_visibility(level)['status'], 'incomplete')
        self.assertEqual(validate_city.verify_visibility({})['status'], 'absent')
        self.assertEqual(validate_city.verify_visibility({'visibility': empty_visibility()})['status'], 'incomplete')

    def test_visibility_validator_rejects_missing_corrupt_and_duplicate_topology(self):
        valid, _ = full_city()
        self.assertTrue(validate_city.verify_visibility(valid)['complete'])
        mutations = [
            ('portal count mismatch', lambda g: g['portals'].pop()),
            ('portal count mismatch', lambda g: g.pop('portal_count')),
            ('missing/duplicate visibility cell id', lambda g: g['cells'].append(copy.deepcopy(g['cells'][0]))),
            ('missing visibility floor cell', lambda g: g['cells'].pop()),
            ('whole-floor volume', lambda g: g['cells'][0]['max'].__setitem__(1, 99)),
            ('unknown visibility portal source', lambda g: g['portals'][0].__setitem__('from', 'unknown')),
            ('unknown visibility portal destination', lambda g: g['portals'][0].__setitem__('to', 'unknown')),
            ('unit axis', lambda g: g['portals'][0].__setitem__('normal', [1, 1, 0])),
            ('outward source boundary', lambda g: g['portals'][0].__setitem__('normal', [0, 0, 1])),
            ('invalid visibility portal bounds', lambda g: g['portals'][0].__setitem__('max', g['portals'][0]['min'])),
            ('duplicate visibility portal', lambda g: g['portals'].__setitem__(1, copy.deepcopy(g['portals'][0]))),
        ]
        for expected, mutate in mutations:
            broken = copy.deepcopy(valid)
            mutate(broken['visibility'])
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                validate_city.verify_visibility(broken)
        broken = copy.deepcopy(valid)
        graph = broken['visibility']
        graph['portals'] = [p for p in graph['portals'] if p['to'] is None]
        graph['portal_count'] = len(graph['portals'])
        with self.assertRaisesRegex(ValueError, 'stair portal count mismatch'):
            validate_city.verify_visibility(broken)


if __name__ == '__main__':
    unittest.main()
