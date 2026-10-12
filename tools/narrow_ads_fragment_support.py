"""Apply the unchanged three-byte limit to a bounded clipped GL source trace.

Inputs are a conditional source geometry supplement, not native observations.
This tool only narrows its required mask; it never changes capture acceptance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from ads_fragment_error_bound import interpolation_error,finite_output_budget


def indices(runs):
    result=set();previous=-1
    for start,count in runs:
        if type(start)!=int or type(count)!=int or start<0 or count<1 or start+count>960*540 or start<=previous:
            raise ValueError('invalid or overlapping run')
        result.update(range(start,start+count));previous=start+count-1
    return result


def runs(values):
    out=[]
    for n in sorted(values):
        if out and n==sum(out[-1]):out[-1][1]+=1
        else:out.append([n,1])
    return out


def triangle_bound(t,sub,overlap):
    if t['kind']!='rigid' or t['texture_bounds']!=[[255,255]]*3 or any(v[3]!=255 for v in t['colors']):
        raise ValueError('outside rigid opaque white-texture fragment scope')
    screen=[[[p[0][0],p[0][1]],[540-p[1][1],540-p[1][0]]] for p in sub['unsnapped_screen']]
    points=[(i%960,539-i//960) for i in overlap]
    xy=[[min(p[0] for p in points),max(p[0] for p in points)],
        [min(p[1] for p in points),max(p[1] for p in points)]]
    interpolation=interpolation_error(screen,sub['reciprocal_w'],sub['colors'],xy,1/256)
    excursion=0.0
    for c in range(3):
        original=[v[c]/255 for v in t['colors']]
        clipped=[v[c] for v in sub['colors']]
        excursion=max(excursion,min(original)-min(v[0] for v in clipped),
                       max(v[1] for v in clipped)-max(original))
    excursion=math.nextafter(excursion,math.inf)
    maxc=max(abs(bound) for v in sub['colors'] for ch in v for bound in ch)
    # A conservative two half-precision conversions/roundings in the straight
    # white-texture fragment path; multiplication by sampled one is exact for
    # an already represented finite operand. Initial normalization must be
    # included in the input intervals BEFORE clipping/setup/extrapolation.
    shader=math.nextafter((maxc+interpolation)*((1+2**-10)**2-1),math.inf)
    return finite_output_budget(interpolation,excursion,shader)


def narrow_frame(frame):
    required=indices(frame['checks']['required_runs'])
    unsafe=set();rows=[]
    for t in frame['triangles']:
        for sid,sub in enumerate(t.get('subtriangles',[])):
            possible=indices(sub['possible_runs'])
            overlap=required&possible
            if not overlap:continue
            row={'mesh':t['mesh'],'triangle':t['triangle'],'subtriangle':sid,
                 'overlap_count':len(overlap)}
            try:
                bound=triangle_bound(t,sub,overlap)
                row['cumulative_byte_bound']=bound
                if bound>3:row['unsafe_reason']='exceeds_existing_three_byte_allowance'
            except (ValueError,OverflowError) as error:
                row['unsafe_reason']=str(error)
            if 'unsafe_reason' in row:unsafe|=possible
            rows.append(row)
    retained=required-unsafe
    return {'frame':frame['frame'],'required_before_fragment':len(required),
            'required_after_fragment':len(retained),'required_runs':runs(retained),
            'removed_required_runs':runs(required-retained),
            'examined_overlapping_subtriangles':len(rows),
            'unsafe_subtriangles':sum('unsafe_reason'in r for r in rows),
            'max_retained_triangle_byte_bound':max((r['cumulative_byte_bound'] for r in rows if 'unsafe_reason'not in r),default=None),
            'triangles':rows,'native_fragment_profile_verified':False,
            'acceptance_verdict':None}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('clipped_trace',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();frames=[];header=None;seen=set()
    with args.clipped_trace.open() as f:
        for line in f:
            record=json.loads(line)
            if 'frame'not in record:
                if header is not None:raise ValueError('multiple trace headers')
                header=record
            else:
                if record['frame'] in seen:raise ValueError('duplicate frame')
                seen.add(record['frame'])
                frames.append(narrow_frame(record))
    if header is None or not frames:raise ValueError('empty source trace')
    report={'schema':'rust-duty-bounded-fragment-supplement/v1',
            'scope':'conditional Mesa26.2.4 rigid-white alpha path, source geometry required mask only',
            'input_sha256':hashlib.sha256(args.clipped_trace.read_bytes()).hexdigest(),
            'input_header':header,'frame_count':len(frames),'frames_with_retained_required_support':sum(r['required_after_fragment']>0 for r in frames),
            'frames_without_retained_required_support':[r['frame'] for r in frames if r['required_after_fragment']==0],
            'frames':frames,'native_fragment_profile_verified':False,'acceptance_complete':False}
    with args.output.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('frames','input_header')},indent=2))


if __name__=='__main__':main()
