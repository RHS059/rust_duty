import unittest
from unittest.mock import patch
from narrow_ads_fragment_support import indices,runs,narrow_frame


class Narrowing(unittest.TestCase):
    def test_runs_reject_overlap_order_and_wrong_scalar_types(self):
        for malformed in [[[0,2],[1,2]],[[3,1],[0,1]],[[True,1]],[[0,0]]]:
            with self.assertRaises(ValueError):indices(malformed)
        self.assertEqual(runs({3,4,5,8}),[[3,3],[8,1]])

    def test_any_possible_unsafe_winner_removes_entire_intersection(self):
        # Required support supplied by the geometry certificate. A second,
        # numerically unsafe potential depth winner invalidates both 2 and 3,
        # regardless of which triangle generated the robust obligation.
        frame={'frame':17,'checks':{'required_runs':[[1,4]]},'triangles':[
            {'mesh':1,'triangle':1,'subtriangles':[{'possible_runs':[[1,4]]}]},
            {'mesh':2,'triangle':2,'subtriangles':[{'possible_runs':[[2,2]],'required_overlap_runs':[[2,1]]}]}]}
        with patch('narrow_ads_fragment_support.triangle_bound',side_effect=[2.9,3.1]):
            result=narrow_frame(frame)
        self.assertEqual(result['required_runs'],[[1,1],[4,1]])
        self.assertEqual(result['removed_required_runs'],[[2,2]])
        self.assertFalse(result['native_fragment_profile_verified'])
        self.assertIsNone(result['acceptance_verdict'])

    def test_unresolved_bound_fails_closed(self):
        frame={'frame':17,'checks':{'required_runs':[[1,4]]},'triangles':[
            {'mesh':1,'triangle':1,'subtriangles':[{'possible_runs':[[0,8]]}]}]}
        with patch('narrow_ads_fragment_support.triangle_bound',side_effect=ValueError('area includes zero')):
            result=narrow_frame(frame)
        self.assertEqual(result['required_runs'],[])
        self.assertEqual(result['unsafe_subtriangles'],1)


if __name__=='__main__':unittest.main()
