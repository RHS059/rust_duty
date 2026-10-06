"""Conservative forward-error bound for Mesa 26.2.4 llvmpipe planes.

This computes a mathematical bound from supplied post-clip vertex intervals.
It does not establish that those intervals contain a native execution, that a
sample is covered, or that the native driver matches the audited source.
No acceptance/profile flag is emitted by this helper.
"""
from dataclasses import dataclass
from itertools import permutations
import math

U = 2.0 ** -23  # one full binary32 ulp relative; permits separate mul/add
TINY = 2.0 ** -126  # conservative allowance even for a flushed subnormal


def up(x):
    if not math.isfinite(x):
        raise ValueError("nonfinite bound")
    return math.nextafter(x, math.inf)


def down(x):
    if not math.isfinite(x):
        raise ValueError("nonfinite bound")
    return math.nextafter(x, -math.inf)


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    def __post_init__(self):
        if not (math.isfinite(self.lo) and math.isfinite(self.hi) and self.lo <= self.hi):
            raise ValueError("invalid interval")

    @classmethod
    def point(cls, x):
        return cls(float(x), float(x))

    @property
    def mag(self):
        return max(abs(self.lo), abs(self.hi))

    @property
    def minabs(self):
        if self.lo <= 0 <= self.hi:
            return 0.0
        return min(abs(self.lo), abs(self.hi))

    def __add__(self, b):
        return Interval(down(self.lo+b.lo), up(self.hi+b.hi))

    def __sub__(self, b):
        return Interval(down(self.lo-b.hi), up(self.hi-b.lo))

    def __mul__(self, b):
        v = [a*z for a in (self.lo,self.hi) for z in (b.lo,b.hi)]
        return Interval(down(min(v)), up(max(v)))

    def __truediv__(self, b):
        if b.minabs == 0:
            raise ValueError("divisor interval contains zero")
        return self * Interval(down(1/b.hi), up(1/b.lo))


@dataclass(frozen=True)
class FloatBound:
    """Range of an ideal real computation, plus absolute rounding error."""
    value: Interval
    error: float = 0.0

    def __post_init__(self):
        if not (math.isfinite(self.error) and self.error >= 0):
            raise ValueError("invalid error bound")

    @classmethod
    def point(cls, x):
        return cls(Interval.point(x))

    @staticmethod
    def rounded(value, propagated):
        error = up(propagated + up(U*up(value.mag+propagated) + TINY))
        if up(value.mag+error)>float.fromhex('0x1.fffffep+127'):
            raise ValueError("binary32 overflow is possible")
        return FloatBound(value,error)

    def __add__(self,b):
        return self.rounded(self.value+b.value,up(self.error+b.error))

    def __sub__(self,b):
        return self.rounded(self.value-b.value,up(self.error+b.error))

    def __mul__(self,b):
        e=up(up(self.value.mag*b.error)+up(b.value.mag*self.error))
        e=up(e+up(self.error*b.error))
        return self.rounded(self.value*b.value,e)

    def __truediv__(self,b):
        value=self.value/b.value
        denominator=down(b.value.minabs-b.error)
        if denominator <= 0:
            raise ValueError("rounded divisor can cross zero")
        e=up(up(self.error+up(value.mag*b.error))/denominator)
        return self.rounded(value,e)


def coefficient_setup(screen):
    """Mesa lp_state_setup.c init_args; screen coords use GL bottom-left."""
    (x0,y0),(x1,y1),(x2,y2)=[[FloatBound(Interval(*v)) for v in p] for p in screen]
    dx01,dy01=x0-x1,y0-y1
    dx20,dy20=x2-x0,y2-y0
    reciprocal=FloatBound.point(1)/(dx01*dy20-dy01*dx20)
    return (dy20*reciprocal,dy01*reciprocal,
            dx20*reciprocal,dx01*reciprocal,
            x0-FloatBound.point(.5),y0-FloatBound.point(.5))


def plane_terms(values,setup):
    a0,a1,a2=values
    dy20,dy01,dx20,dx01,x0,y0=setup
    da01,da20=a0-a1,a2-a0
    dadx=da01*dy20-da20*dy01
    dady=da20*dx01-da01*dx20
    origin=a0-(dadx*x0+dady*y0)
    return origin,dadx,dady


def plane(values,setup,xy_range):
    """Separate multiply/add bounds also contain tighter FMA execution."""
    origin,dadx,dady=plane_terms(values,setup)
    x,y=[FloatBound(Interval(*v)) for v in xy_range]
    return origin+dadx*x+dady*y


def interpolation_error(screen,reciprocal_w,colors,xy_range,snap_displacement=0.0):
    """Maximum normalized RGB error for *covered* points in xy_range.

    Inputs are actual post-clip, pre-setup shader values, bounded independently.
    Colors are normalized intervals and may include normalization/clipping
    perturbations. The caller must account for those perturbations separately.
    The exact perspective result lies in their convex channel envelope because
    coverage and positive reciprocal-w are independent prerequisites. A supplied
    snap_displacement bounds each coordinate's movement between interpolator
    setup and coverage. Covered points of the snapped triangle are within that
    displacement of a convex point of the unsnapped triangle. Its exact plane
    gradients then bound any resulting extrapolation, separately from roundoff.
    """
    if not (math.isfinite(snap_displacement) and snap_displacement>=0):
        raise ValueError("invalid snapping displacement")
    if len(screen)!=3 or len(reciprocal_w)!=3 or len(colors)!=3:
        raise ValueError("exactly three post-clip vertices are required")
    result=[]
    for order in permutations(range(3)):
        setup=coefficient_setup([screen[i] for i in order])
        qs=[FloatBound(Interval(*reciprocal_w[i])) for i in order]
        qmin=min(q.value.lo for q in qs)
        qmax=max(q.value.hi for q in qs)
        if qmin <= 0:
            raise ValueError("positive finite reciprocal-w is required")
        qp=plane(qs,setup,xy_range)
        qt=plane_terms(qs,setup)
        dq=up(snap_displacement*up(qt[1].value.mag+qt[2].value.mag))
        if down(qmin-dq)<=0:
            raise ValueError("snapping extrapolation can cross reciprocal-w zero")
        # For an independently certified covered point, exact interpolated
        # reciprocal-w is a convex combination. Tighten range, retain error.
        qp=FloatBound(Interval(down(qmin-dq),up(qmax+dq)),qp.error)
        errors=[]
        for c in range(3):
            cs=[FloatBound(Interval(*colors[i][c])) for i in order]
            product=[cs[i]*qs[i] for i in range(3)]
            numerator=plane(product,setup,xy_range)
            nt=plane_terms(product,setup)
            dn=up(snap_displacement*up(nt[1].value.mag+nt[2].value.mag))
            # Convexity also bounds the exact, pre-perspective numerator.
            numerator=FloatBound(Interval(down(min(p.value.lo for p in product)-dn),
                                          up(max(p.value.hi for p in product)+dn)),numerator.error)
            # Mesa emits fdiv(1,q), then multiplication. Do not model one div.
            out=numerator*(FloatBound.point(1)/qp)
            cmag=max(v.value.mag for v in cs)
            extrap=up(up(dn+up(cmag*dq))/down(qmin-dq))
            errors.append(up(out.error+extrap))
        result.append(max(errors))
    return max(result)


def mul_unorm8(a,b):
    """Mesa lp_build_mul_norm, unsigned 8-bit, exact integer expansion."""
    if not 0<=a<=255 or not 0<=b<=255:
        raise ValueError("UNORM8 operand out of range")
    t=a*b+128
    return (t+(t>>8))>>8


def finite_output_budget(interpolation, normalized_color_error=0.0,
                         shader_rounding_error=0.0):
    if min(interpolation,normalized_color_error,shader_rounding_error)<0:
        raise ValueError("negative error")
    # Unsized GL_RGBA storage must first be bound to the pinned UNORM8 path.
    # One final source-to-UNORM8 rounding; PNG row/copy operations are lossless.
    total=up(up(interpolation+normalized_color_error)+shader_rounding_error)
    return up(up(255*total)+0.5001)
