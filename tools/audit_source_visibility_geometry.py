#!/usr/bin/env python3
"""Emit a versioned bounded-source supplement, preserving original evidence."""
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
from source_visibility_clipping import I, Unresolved, clip_xy_variants, project, edge

def mask(runs):return {i for start,length in runs for i in range(start,start+length)}
def runs(values):
 out=[]
 for v in sorted(values):
  if out and out[-1][0]+out[-1][1]==v:out[-1][1]+=1
  else:out.append([v,1])
 return out

def vector_samples(poly):
 if len(poly)<3:return set(),set()
 minx=max(0,math.ceil(min(v[0].lo for v in poly)-.5));maxx=min(959,math.floor(max(v[0].hi for v in poly)-.5))
 miny=max(0,math.ceil(min(v[1].lo for v in poly)-.5));maxy=min(539,math.floor(max(v[1].hi for v in poly)-.5))
 if minx>maxx or miny>maxy:return set(),set()
 xx,yy=np.meshgrid(np.arange(minx,maxx+1),np.arange(miny,maxy+1));x=xx.ravel()+.5;y=yy.ravel()+.5;ids=(yy*960+xx).ravel()
 keep=~((x<64)&(y<22));x=x[keep];y=y[keep];ids=ids[keep]
 reqplus=np.ones(len(x),dtype=bool);reqminus=reqplus.copy();posplus=reqplus.copy();posminus=reqplus.copy()
 def mul_bounds(a,lo,hi):
  v=[a.lo*lo,a.lo*hi,a.hi*lo,a.hi*hi]
  return np.nextafter(np.minimum.reduce(v),-np.inf),np.nextafter(np.maximum.reduce(v),np.inf)
 for a,b in zip(poly,poly[1:]+poly[:1]):
  dx=b[0].sub(a[0]);dy=b[1].sub(a[1]);
  l1,h1=mul_bounds(dx,np.nextafter(y-a[1].hi,-np.inf),np.nextafter(y-a[1].lo,np.inf))
  l2,h2=mul_bounds(dy,np.nextafter(x-a[0].hi,-np.inf),np.nextafter(x-a[0].lo,np.inf))
  lo=np.nextafter(l1-h2,-np.inf);hi=np.nextafter(h1-l2,np.inf)
  reqplus&=lo>0;reqminus&=hi<0;posplus&=hi>=0;posminus&=lo<=0
 return set(map(int,ids[reqplus|reqminus])),set(map(int,ids[posplus|posminus]))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--trace',type=Path,required=True);ap.add_argument('--native',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--summary',type=Path,required=True);a=ap.parse_args()
 native={r['frame']:r for r in map(json.loads,a.native.read_text().splitlines()[1:])}
 report={'schema':'rust-duty-bounded-geometry-supplement/v1','trace_sha256':hashlib.sha256(a.trace.read_bytes()).hexdigest(),'native_source_jsonl_sha256':hashlib.sha256(a.native.read_bytes()).hexdigest(),'native_profile_binding_verified':False,'acceptance_verdict':None,'backend_implementation':'Mesa26.2.4 draw_pipe_clip float32 operational profile; not a native-execution observation','frames':[]}
 with a.trace.open() as f,a.output.open('x') as out:
  header=json.loads(next(f));assert header['backend_profile'].startswith('opengl:'), 'Mesa clipping model is OpenGL-only';out.write(json.dumps({'schema':report['schema'],'backend_implementation':report['backend_implementation'],'native_profile_binding_verified':False,'acceptance_verdict':None})+'\n')
  for line in f:
   row=json.loads(line);orig=native[row['frame']]
   keys=['required_contrast_runs','possible_support_runs','native_gameplay','native_time','unsupported_clip_triangles']
   assert all(row[k]==orig[k] for k in keys),'local source replay differs from native source record'
   domains=[m['domain'] for m in row['geometry_domain']]
   oldreq=mask(orig['required_contrast_runs']);oldpos=mask(orig['possible_support_runs']);robust=set();possible=set();unsafe=set();emitted=[];unresolved=[];generated=0;clipped=0
   for t in row['triangle_trace']:
    try:variants=clip_xy_variants(t['clip'], t['colors'])
    except Unresolved as e:
     unresolved.append({'kind':t['kind'],'mesh':t['mesh'],'triangle':t['triangle'],'reason':str(e)});continue
    tr=None;tp=set();subtri=[];max_generated=0
    for variant_index,(poly,n) in enumerate(variants):
     max_generated=max(max_generated,n)
     proj=[project(v) for v in poly];screen=[p[0] for p in proj]
     vr=set();vp=set()
     for i in range(1,len(poly)-1):
      fan=[0,i,i+1];rr,pp=vector_samples([screen[j] for j in fan]);vr|=rr;vp|=pp
      if pp:subtri.append({'variant':variant_index,'fan':fan,'clip':[[x.wire() for x in poly[j][:4]] for j in fan],'colors':[[x.wire() for x in poly[j][4:7]] for j in fan],'unsnapped_screen':[[x.wire() for x in project(poly[j],snap=False)[0]] for j in fan],'screen':[[x.wire() for x in screen[j]] for j in fan],'reciprocal_w':[proj[j][1].wire() for j in fan],'possible_runs':runs(pp),'required_overlap_runs':runs(pp&oldreq),'robust_runs':runs(rr)})
     tr=vr if tr is None else tr&vr;tp|=vp
    generated+=max_generated;clipped+=bool(max_generated)
    robust|=(tr or set()) if t['safe_contrast'] else set();possible|=tp
    if not t['safe_contrast']:unsafe|=tp
    if tp:emitted.append({k:t[k] for k in ['kind','mesh','triangle','colors','texture_bounds','safe_contrast']}|{'generated_vertices':max_generated,'variant_count':len(variants),'subtriangles':subtri})
   required=((robust-unsafe)&oldreq) if not unresolved else set()
   # A conservative envelope combines both old and new possible sets; no
   # original support obligation is discarded. Required samples only narrow.
   expanded_possible=possible|oldpos
   checks={'all_source_domain_nodes_supported':all(d['normal_or_exact_zero_no_overflow'] for d in domains),'local_native_masks_state_equal':True,'unresolved_clipping_triangles':len(unresolved),'minimum_nonzero_dyadic_exponent':min(d['minimum_nonzero_dyadic_exponent'] for d in domains),'maximum_rounded_magnitude_upper':max(d['maximum_rounded_magnitude_upper'] for d in domains),'source_triangles_considered':len(row['triangle_trace']),'clipped_source_triangles':clipped,'generated_vertices':generated,'required_original':len(oldreq),'required_retained':len(required),'required_original_not_reproved':len(oldreq-required),'possible_original':len(oldpos),'possible_generated':len(possible),'possible_additional':len(possible-oldpos),'possible_original_not_reproved':len(oldpos-possible),'required_runs':runs(required),'possible_runs':runs(expanded_possible),'unresolved':unresolved,'original_profile_flags_unchanged':True,'native_geometry_profile_verified':False}
   report['frames'].append({'frame':row['frame'],**checks})
   out.write(json.dumps({'frame':row['frame'],'checks':checks,'triangles':emitted},separators=(',',':'))+'\n');out.flush()
   print(row['frame'],'triangles',len(emitted),'clip',clipped,'unresolved',len(unresolved),'required',len(required),'/',len(oldreq),'possible+',len(possible-oldpos),flush=True)
 report['passed_source_domain']=all(f['all_source_domain_nodes_supported'] for f in report['frames'])
 report['passed_clipping_model']=all(not f['unresolved_clipping_triangles'] and f['required_retained'] for f in report['frames'])
 report['bounded_mask_native_coverage_inferred_from_retained_comparator']=False
 report['retained_native_comparator_binding_required']=True
 report['limitations']=['Mesa implementation model applies to OpenGL llvmpipe only; not evidence of DX12 clipping behavior.','Current-host replay matches original masks and full per-frame records; does not itself prove intermediate native source vertex bit identity.','RGB/interpolation and actual Mesa binary/build binding require separate evidence.','Required masks narrow from original obligations; possible masks expand by independently computed clipped geometry. Original files and original flags remain unchanged.']
 a.summary.write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
