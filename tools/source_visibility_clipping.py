#!/usr/bin/env python3
"""Bound Mesa 26.2.4's X/Y clipped geometry. Never asserts native execution.

All operations use outward binary64 intervals, plus binary32 rounding and an
explicit absolute flush/subnormal allowance. Uncertain clipping branches fail
closed; they are not chosen from a nominal evaluation. Original masks stay intact.
"""
from dataclasses import dataclass
import math
U=2.0**-23
TINY=2.0**-126
@dataclass(frozen=True)
class I:
    lo:float
    hi:float
    @staticmethod
    def p(x):return I(float(x),float(x))
    def add(self,b):return outward(self.lo+b.lo,self.hi+b.hi)
    def sub(self,b):return outward(self.lo-b.hi,self.hi-b.lo)
    def mul(self,b):
        x=[self.lo*b.lo,self.lo*b.hi,self.hi*b.lo,self.hi*b.hi]
        return outward(min(x),max(x))
    def div(self,b):
        if b.lo<=0<=b.hi:raise Unresolved('division denominator includes zero')
        return self.mul(outward(1/b.hi,1/b.lo))
    def neg(self):return I(-self.hi,-self.lo)
    def rounded(self,n=1):
        # n binary32 operations, allowing flush of each subnormal result.
        e=max(abs(self.lo),abs(self.hi))*((n*U)/(1-n*U))+n*TINY
        return outward(self.lo-e,self.hi+e)
    def hull(self,b):return I(min(self.lo,b.lo),max(self.hi,b.hi))
    def wire(self):return [self.lo,self.hi]
class Unresolved(ValueError):pass
def outward(a,b):return I(math.nextafter(a,-math.inf),math.nextafter(b,math.inf))
def dist(v,axis,sign):return v[3].add(v[axis] if sign==1 else v[axis].neg()).rounded(1)
def status(d):
    if d.lo>=0:return True
    if d.hi<0:return False
    raise Unresolved('clip-plane side not determined over original interval')
def interpolate(a,b,da,db):
    # Mesa selects the closest endpoint. Hull both algebraically equivalent
    # source expressions so the branch on distance magnitude need not be known.
    denominator=db.sub(da).rounded()
    t1=da.neg().div(denominator).rounded()
    t2=db.div(denominator).rounded()
    one=[];two=[]
    for x,y in zip(a,b):
        one.append(x.add(t1.mul(y.sub(x).rounded()).rounded()).rounded())
        two.append(y.add(t2.mul(x.sub(y).rounded()).rounded()).rounded())
    return [x.hull(y) for x,y in zip(one,two)]
def clip_xy(vertices, colors=None):
    vertices=[[I(*b) for b in v] for v in vertices]
    if colors is not None:
        vertices=[v+[I.p(c/255).rounded() for c in color[:3]] for v,color in zip(vertices,colors)]
    if any(v[3].lo<=0 or v[2].add(v[3]).lo<=0 or v[3].sub(v[2]).lo<=0 for v in vertices):
        raise Unresolved('eye/near/far clipping unsupported')
    # draw_context.c planes0..3 and draw_pipe_clip.c ascending ffs order.
    generated=0
    planes=[]
    for axis,sign in [(0,-1),(0,1),(1,-1),(1,1)]:
        original=[dist(v,axis,sign) for v in vertices]
        if all(d.lo>=0 for d in original):continue
        if not any(d.hi<0 for d in original):
            raise Unresolved('original clipmask plane uncertain')
        planes.append((axis,sign))
    for axis,sign in planes:
        if not vertices:break
        distances=[dist(v,axis,sign) for v in vertices]
        signs=[status(d) for d in distances]
        out=[]
        for i,a in enumerate(vertices):
            j=(i+1)%len(vertices)
            if signs[i]:out.append(a)
            if signs[i]!=signs[j]:
                out.append(interpolate(a,vertices[j],distances[i],distances[j]));generated+=1
        vertices=out
    return vertices,generated
def project(v, snap=True):
    if v[3].lo<=0:raise Unresolved('generated w includes zero')
    reciprocal=I.p(1).div(v[3]).rounded()
    # Mesa uses x*oow*scale+trans, including generated clipping vertices.
    x=v[0].mul(reciprocal).rounded().mul(I.p(480)).rounded().add(I.p(480)).rounded()
    y=v[1].mul(reciprocal).rounded().mul(I.p(-270)).rounded().add(I.p(270)).rounded()
    # Existing profile admits a complete1/256pixel displacement. Bound the
    # generated vertex too; retain the exact existing displacement constant.
    eps=I(-1/256,1/256)
    return ([x.add(eps),y.add(eps)] if snap else [x,y]),reciprocal
def edge(a,b,p):return b[0].sub(a[0]).mul(p[1].sub(a[1])).sub(b[1].sub(a[1]).mul(p[0].sub(a[0])))
def samples(poly,points):
    if len(poly)<3:return set(),set()
    required=set();possible=set()
    for index in points:
        p=[I.p(index%960+.5),I.p(index//960+.5)]
        edges=[edge(poly[i],poly[(i+1)%len(poly)],p) for i in range(len(poly))]
        if all(e.lo>0 for e in edges) or all(e.hi<0 for e in edges):required.add(index)
        if all(e.hi>=0 for e in edges) or all(e.lo<=0 for e in edges):possible.add(index)
    return required,possible

def clip_xy_variants(vertices, colors=None):
    """Enumerate all interval-consistent original clip masks and side branches.

    Each returned polygon is an enclosure, not a measured hardware polygon.
    Unknown signs branch both ways. A cap is fail-closed, never truncation.
    """
    import itertools
    original=[[I(*b) for b in v] for v in vertices]
    if colors is not None:
        # Allow c/255 conversion and an optional 10-bit-significand lowp store.
        rel=(1+2**-10)**2-1
        original=[v+[outward(c/255-abs(c/255)*rel,c/255+abs(c/255)*rel) for c in color[:3]] for v,color in zip(original,colors)]
    if any(v[3].lo<2**-20 or v[2].add(v[3]).lo<=0 or v[3].sub(v[2]).lo<=0 for v in original):
        raise Unresolved('eye/near/far or small-w clipping domain unsupported')
    states=[(original,0)]
    for axis,sign in [(0,-1),(0,1),(1,-1),(1,1)]:
        od=[dist(v,axis,sign) for v in original]
        if all(d.lo>=0 for d in od):continue
        mask_certain=any(d.hi<0 for d in od)
        next_states=[]
        for poly,generated in states:
            if any(v[3].lo < 2**-20 for v in poly):
                raise Unresolved('generated vertex leaves bounded-w domain')
            if len(poly)<3:
                next_states.append((poly,generated))
                continue
            if not mask_certain:next_states.append((poly,generated))
            ds=[dist(v,axis,sign) for v in poly]
            options=[(True,) if d.lo>=0 else (False,) if d.hi<0 else (False,True) for d in ds]
            for flags in itertools.product(*options):
                # Narrow only the explicit dp operands according to branch.
                signed=[I(max(d.lo,0),d.hi) if inside else I(d.lo,min(d.hi,0)) for d,inside in zip(ds,flags)]
                out=[];n=generated
                for i,a in enumerate(poly):
                    j=(i+1)%len(poly)
                    if flags[i]:out.append(a)
                    if flags[i]!=flags[j]:
                        b=poly[j];da=signed[i];db=signed[j];den=db.sub(da).rounded()
                        # Opposite-sign distances make denom an addition of
                        # magnitudes. The native branch guarantees it nonzero.
                        # With w>=2^-20, any nonzero float32 x+-w distance near
                        # a side plane has quantum>=2^-44, excluding underflow.
                        # Allow ratio error through rounded denominator/divide.
                        tmax=(1+U)/(1-U)+2**-100
                        range_t=I(-2**-100,tmax)
                        if den.lo<=0<=den.hi:
                            t1=t2=range_t
                        else:
                            q1=da.neg().div(den).rounded();q2=db.div(den).rounded()
                            t1=I(max(range_t.lo,q1.lo),min(range_t.hi,q1.hi));t2=I(max(range_t.lo,q2.lo),min(range_t.hi,q2.hi))
                        one=[];two=[]
                        for x,y in zip(a,b):
                            one.append(x.add(t1.mul(y.sub(x).rounded()).rounded()).rounded())
                            two.append(y.add(t2.mul(x.sub(y).rounded()).rounded()).rounded())
                        out.append([x.hull(y) for x,y in zip(one,two)]);n+=1
                next_states.append((out,n))
                if len(next_states)>256:raise Unresolved('clipping branch budget exceeded')
        states=next_states
    return states
