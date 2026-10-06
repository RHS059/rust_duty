import math
import random
import struct
import unittest
from ads_fragment_error_bound import FloatBound, Interval, interpolation_error, mul_unorm8, finite_output_budget


def f32(x):
    return struct.unpack('f',struct.pack('f',x))[0]


class Bounds(unittest.TestCase):
    def test_unorm_all_65536_products_and_opaque_blend_endpoints(self):
        for a in range(256):
            for b in range(256):
                self.assertEqual(mul_unorm8(a,b),math.floor(a*b/255+.5))
            self.assertEqual(mul_unorm8(a,255),a)
            self.assertEqual(mul_unorm8(a,0),0)

    def test_roundoff_bounds_contain_sampled_f32_operations(self):
        rng=random.Random(915812)
        for _ in range(2000):
            a,b=[f32(rng.uniform(.01,100)) for _ in range(2)]
            aa,bb=FloatBound.point(a),FloatBound.point(b)
            for ideal,actual,bound in [(a+b,f32(a+b),aa+bb),(a-b,f32(a-b),aa-bb),
                                        (a*b,f32(a*b),aa*bb),(a/b,f32(a/b),aa/bb)]:
                self.assertLessEqual(abs(actual-ideal),bound.error)
                self.assertLessEqual(bound.value.lo,ideal)
                self.assertGreaterEqual(bound.value.hi,ideal)

    def test_opaque_alpha_survives_reciprocal_and_half_conversion(self):
        # Equal homogeneous alpha-one planes produce the same finite q.
        # One full ulp each for reciprocal and multiply is conservative.
        u=2**-23
        low=(1-u)**2
        # Even a following half conversion rounded toward zero loses less
        # than one relative half ulp. UNORM8 still rounds to alpha 255.
        low*=1-2**-10
        self.assertGreater(low,254.5/255)
        self.assertEqual(f32(f32(1/255)*255),1)
        half=lambda x: struct.unpack('e',struct.pack('e',x))[0]
        self.assertEqual(half(half(1/255)*255),1)

    def test_nonfinite_degenerate_and_reciprocal_zero_rejected(self):
        with self.assertRaises(ValueError): Interval(0,math.inf)
        with self.assertRaises(ValueError): FloatBound.point(1)/FloatBound(Interval(-1,1))
        with self.assertRaises(ValueError): FloatBound.point(3e38)*FloatBound.point(2)
        screen=[[[1,1],[1,1]]]*3
        with self.assertRaises(ValueError):
            interpolation_error(screen,[[1,1]]*3,[[[.3,.3]]*3]*3,[[1,1],[1,1]])

    def test_well_conditioned_triangle_fits_fixed_three_byte_budget(self):
        screen=[[[20,20],[20,20]],[[500,500],[30,30]],[[100,100],[400,400]]]
        err=interpolation_error(screen,[[2,2],[3,3],[4,4]],
            [[[c,c]]*3 for c in [.1,.2,.4]],[[20,500],[20,400]])
        self.assertLess(finite_output_budget(err,.4/1024,3*.4/1024),3)

    def test_unbounded_conditioning_cannot_be_approved_by_precision_only(self):
        screen=[[[500,500],[400,400]],[[500.01,500.01],[400,400]],
                [[500.02,500.02],[400.00001,400.00001]]]
        try:
            err=interpolation_error(screen,[[2,2],[3,3],[4,4]],
                [[[c,c]]*3 for c in [.1,.2,.4]],[[500,501],[400,401]])
        except ValueError:
            return
        self.assertGreater(finite_output_budget(err),3)

    def test_snapped_coverage_adds_explicit_extrapolation_allowance(self):
        screen=[[[0,0],[0,0]],[[10,10],[0,0]],[[0,0],[10,10]]]
        args=(screen,[[1,1]]*3,[[[c,c]]*3 for c in [0,1,0]],[[0,10],[0,10]])
        base=interpolation_error(*args)
        snapped=interpolation_error(*args,snap_displacement=1/256)
        self.assertGreater(snapped,base+1/256/10)


if __name__=='__main__': unittest.main()
