"""Auditable screen-space weapon diagnostics. No tracking, fitting, retiming or score."""
from __future__ import annotations
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import statistics

SCHEMA = 'rust-duty-weapon-comparison/v1'
STATES = {'visible', 'occluded', 'tracker_failed', 'uncertain', 'out_of_frame', 'missing'}
MAX_BYTES = 32 * 1024 * 1024
MAX_FRAMES = 20000

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def strict_json(data):
    if len(data) > MAX_BYTES:
        raise ValueError('Input exceeds 32 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=reject)

def number(value, name, low=-1e9, high=1e9):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid ' + name)
    return float(value)

def integer(value, name, low=0, high=2**53):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid ' + name)
    return value

def rational(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(name + ' must be [integer numerator, positive denominator]')
    return Fraction(integer(value[0], name, -2**53), integer(value[1], name, 1))

def ratio(value):
    return [value.numerator, value.denominator]

def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError('Require ' + name)
    return value

def artifact(value):
    text(value.get('name'), 'artifact name')
    digest = value.get('sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Require lowercase artifact SHA256')
    return value

def point(value, viewport):
    if not isinstance(value, dict) or value.get('state') not in STATES:
        raise ValueError('Point needs explicit observability state')
    text(value.get('method'), 'point observation/evaluation method')
    if 'confidence' in value:
        number(value['confidence'], 'model confidence', 0, 1)
    if value['state'] == 'visible':
        xy = value.get('xy')
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError('Visible point needs xy')
        for axis, bound in zip(xy, viewport):
            number(axis, 'visible pixel coordinate', 0, bound)
        number(value.get('uncertainty_px'), 'visible pixel uncertainty', 0, max(viewport))
    elif value.get('xy') is not None:
        if len(value['xy']) != 2:
            raise ValueError('Point xy must have two coordinates')
        for axis in value['xy']:
            number(axis, 'nonvisible pixel coordinate', -100000, 100000)
    return value

def validate(doc):
    if doc.get('schema') != SCHEMA:
        raise ValueError('Unsupported comparison schema')
    text(doc.get('action'), 'independently reviewed action')
    text(doc.get('rubric_version'), 'rubric version (pending allowed)')
    if doc.get('kind') not in ('event', 'loop'):
        raise ValueError('kind must be event or loop')
    source, candidate = doc['source'], doc['candidate']
    artifact(source['artifact']); artifact(candidate['artifact'])
    text(candidate.get('author'), 'candidate author')
    if candidate.get('space') != 'evaluated-camera-pixels':
        raise ValueError('Candidate must use evaluated camera projection, not local bones')
    for view in (source['viewport'], candidate['viewport']):
        if not isinstance(view, list) or len(view) != 2:
            raise ValueError('Viewport requires width,height')
        for v in view:
            integer(v, 'viewport dimension', 1, 16384)
    tb = rational(source['time_base'], 'source time_base')
    if tb <= 0:
        raise ValueError('Time base must be positive')
    window = source['window_frames']
    if len(window) != 2 or any(type(v) is not int or v < 0 for v in window) or not 2 <= window[1] - window[0] <= MAX_FRAMES:
        raise ValueError('Require complete bounded half-open source window')
    reg = doc['registration']
    allowed = {'mode', 'source_scale', 'candidate_scale', 'source_anchor_pts', 'candidate_anchor_time', 'phase_offset', 'frozen_record'}
    if set(reg) != allowed or reg['mode'] != 'frozen-unwarped':
        raise ValueError('Only one frozen scale and phase mapping; unknown/per-frame registration prohibited')
    text(reg['frozen_record'], 'pre-candidate registration record')
    ss = number(reg['source_scale'], 'source scale', .01, 100)
    cs = number(reg['candidate_scale'], 'candidate scale', .01, 100)
    anchor = integer(reg['source_anchor_pts'], 'source anchor PTS', -2**53)
    candidate_anchor = rational(reg['candidate_anchor_time'], 'candidate anchor time')
    phase = rational(reg['phase_offset'], 'single phase offset')
    if abs(phase) > 600:
        raise ValueError('Phase offset out of bounds')
    norm = doc['normalization']
    if norm['L_px'] is not None:
        number(norm['L_px'], 'fixed reference visible-axis L', .01, 100000)
    text(norm['definition'], 'L definition and frozen source evidence')
    integer(doc['metrics_stride'], 'fixed metrics stride', 1, 60)
    baseline = integer(doc['baseline_frame'], 'fixed pre-event baseline')
    if not window[0] <= baseline < window[1]:
        raise ValueError('Baseline must be inside window')
    landmarks = doc['landmarks']
    if not isinstance(landmarks, list) or not 3 <= len(landmarks) <= 16:
        raise ValueError('Require 3..16 identified rigid weapon landmarks')
    names = [text(p['id'], 'landmark id') for p in landmarks]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate landmark id')
    for p in landmarks:
        text(p.get('physical_point'), 'physical point correspondence')
    axis = doc['axis_landmarks']
    if len(axis) != 2 or len(set(axis)) != 2 or any(p not in names for p in axis):
        raise ValueError('Require two distinct physical axis landmarks')
    rows = doc['samples']
    if not isinstance(rows, list) or len(rows) != window[1] - window[0]:
        raise ValueError('Every source frame required; missing rows cannot hide errors')
    previous_pts = None
    for expected, row in zip(range(*window), rows):
        if row['frame'] != expected or type(row['frame']) is not int:
            raise ValueError('Source frame indices must cover window consecutively')
        pts = integer(row['source_pts'], 'observed source PTS', -2**53)
        if previous_pts is not None and pts <= previous_pts:
            raise ValueError('Decoded PTS must strictly increase')
        previous_pts = pts
        expected_time = (pts - anchor) * tb + candidate_anchor + phase
        if rational(row['candidate_time'], 'candidate evaluation time') != expected_time:
            raise ValueError('PTS mapping mismatch; speed must stay exactly 1 with one frozen offset')
        for side, view in (('reference', source['viewport']), ('candidate', candidate['viewport'])):
            if set(row[side]) != set(names):
                raise ValueError('Every declared landmark needs an explicit state on every frame')
            for name in names:
                point(row[side][name], view)
    phase_names = set()
    for phase_doc in doc.get('phases', []):
        if phase_doc.get('name') in phase_names:
            raise ValueError('Duplicate phase name')
        phase_names.add(phase_doc.get('name'))
        text(phase_doc.get('name'), 'phase name')
        bounds = phase_doc['window_frames']
        if len(bounds) != 2 or any(type(v) is not int for v in bounds) or not window[0] <= bounds[0] < bounds[1] <= window[1]:
            raise ValueError('Phase bounds must be inside complete source window')
    events = doc.get('events', [])
    if not isinstance(events, list) or len(events) > 64:
        raise ValueError('Invalid event list')
    seen = set()
    pts_by_frame = {r['frame']: r['source_pts'] for r in rows}
    for event in events:
        name = text(event['name'], 'event name')
        if name in seen:
            raise ValueError('Duplicate event name')
        seen.add(name)
        text(event['observation'], 'visible event definition, not input-button inference')
        sf = event['source_frame_interval']
        ct = event.get('candidate_time_interval')
        if not isinstance(sf, list) or len(sf) != 2 or any(type(f) is not int or f not in pts_by_frame for f in sf) or sf[0] > sf[1]:
            raise ValueError('Event source bracket must name observed window frames')
        if ct is not None and (len(ct) != 2 or rational(ct[0], 'event time') > rational(ct[1], 'event time')):
            raise ValueError('Invalid candidate event bracket')
    return doc

def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lo = math.floor(position); hi = math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)

def stats(values):
    if not values:
        return None
    return {'rms': math.sqrt(statistics.mean(v*v for v in values)), 'p95': percentile(values, .95), 'max': max(values), 'count': len(values)}

def decision(low, high, threshold):
    # Bounds touching a limit are inconclusive; these are annotation bounds, not CIs.
    return 'within_threshold' if high < threshold else 'outside_threshold' if low > threshold else 'inconclusive'

def interval_stats(errors, uncertainties, threshold):
    lower = stats([max(0, e-u) for e, u in zip(errors, uncertainties)])
    upper = stats([e+u for e, u in zip(errors, uncertainties)])
    return {'lower': lower, 'upper': upper, 'threshold': threshold,
            'threshold_state': decision(lower['rms'], upper['rms'], threshold) if lower and threshold is not None else 'unsupported'}

def circular_delta(a, b):
    return (a-b+180) % 360 - 180

def unwrapped(values):
    result = []
    for v in values:
        result.append(v if not result else result[-1]+circular_delta(v, result[-1]))
    return result

def compare(doc, supplied_artifacts=None, decoded_pts=None):
    validate(doc)
    artifacts = supplied_artifacts or {}
    pts_witness = {'verified_against_supplied_map': False, 'source_video_bytes_verified': False}
    if decoded_pts is not None:
        pts_bytes = decoded_pts if isinstance(decoded_pts, bytes) else json.dumps(decoded_pts,sort_keys=True,separators=(',',':')).encode()
        pts_doc = strict_json(pts_bytes)
        if 'time_base' in pts_doc and rational(pts_doc['time_base'],'PTS map time_base') != rational(doc['source']['time_base'],'source time_base'):
            raise ValueError('Decoded PTS map time base differs from source declaration')
        if 'source_sha256' in pts_doc and pts_doc['source_sha256'] != doc['source']['artifact']['sha256']:
            raise ValueError('Decoded PTS map source identity differs')
        for row in doc['samples']:
            if row['frame'] >= len(pts_doc['frames']) or integer(pts_doc['frames'][row['frame']]['pts'],'decoded map PTS',-2**53) != row['source_pts']:
                raise ValueError('Source PTS differs from independently supplied decoded frame map')
        pts_witness = {'verified_against_supplied_map': True, 'source_video_bytes_verified': False, 'map_sha256': sha256(pts_bytes), 'decoded_frame_count': len(pts_doc['frames']), 'scope':'frame-index and integer-PTS matching only; pixel/annotation provenance not verified', 'time_base_metadata_matched': 'time_base' in pts_doc, 'source_identity_metadata_matched': 'source_sha256' in pts_doc}
    reg = doc['registration']; ss = reg['source_scale']; cs = reg['candidate_scale']
    L = doc['normalization']['L_px']; stride = doc['metrics_stride']
    rows = doc['samples']; selected = rows[::stride]; names = [p['id'] for p in doc['landmarks']]
    result = {'schema': 'rust-duty-weapon-diagnostics/v1', 'status': 'diagnostic', 'action': doc['action'],
        'rubric_version': doc['rubric_version'], 'score': None, 'artistic_approval': False,
        'score_reason': 'No percentage computed. Frozen event rubric and independent complete-clip review are separate requirements.',
        'input_sha256': sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()),
        'code_sha256': sha256(Path(__file__).read_bytes()) if Path(__file__).is_file() else None,
        'registration': reg, 'normalization': doc['normalization'],
        'landmark_definitions': doc['landmarks'], 'declared_annotation_review': doc.get('annotation_review'), 'source_window': doc['source']['window_frames'],
        'metrics_stride': stride, 'native_frame_count': len(rows), 'metric_frame_count': len(selected),
        'decoded_pts_witness': pts_witness, 'provenance': {}, 'landmarks': {}, 'events': [], 'hard_gate_findings': [], 'unsupported': [],
        'reviewer': {'status': 'pending', 'author': doc['candidate']['author'], 'whole_clip_review': None},
        'limits': ['2D screen projection does not establish 3D orientation, contact, anatomical or export/runtime correctness.',
                   'Annotation uncertainty is a conservative bound, not a statistical confidence interval.',
                   'No alignment is fitted, no points tracked automatically, no missing evidence awarded.']}
    for side in ('source', 'candidate'):
        art = doc[side]['artifact']; blob = artifacts.get(art['name'])
        if blob is not None and sha256(blob) != art['sha256']:
            raise ValueError('Supplied artifact hash mismatch: ' + art['name'])
        result['provenance'][side] = {**art, 'bytes_verified': blob is not None}
    result['decoded_pts_witness']['source_video_bytes_verified'] = result['provenance']['source']['bytes_verified']
    pooled_raw = []; pooled_centered = []; pooled_uncertainty = []
    baseline_row = next(r for r in rows if r['frame'] == doc['baseline_frame'])
    worst = []
    for name in names:
        counts = {side: dict(Counter(r[side][name]['state'] for r in rows)) for side in ('reference', 'candidate')}
        missing = [r['frame'] for r in rows if r['reference'][name]['state'] == 'visible' and r['candidate'][name]['state'] != 'visible']
        if missing:
            result['hard_gate_findings'].append({'kind': 'candidate_not_observable_when_source_visible', 'landmark': name, 'frames': missing})
        usable = [r for r in selected if r['reference'][name]['state'] == r['candidate'][name]['state'] == 'visible']
        coverage = len(usable) / len(selected)
        item = {'native_state_counts': counts, 'comparable_samples': len(usable), 'scheduled_samples': len(selected), 'coverage': coverage,
                'native_coverage': coverage_report(rows,name),
                'phase_coverage': {p['name']:coverage_report([r for r in rows if p['window_frames'][0] <= r['frame'] < p['window_frames'][1]],name) for p in doc.get('phases',[])},
                'raw': None, 'mean_centered': None, 'fixed_baseline_displacement': None, 'amplitudes': None}
        if item['native_coverage']['comparable_over_planned'] < .8:
            result['unsupported'].append(name + ': native comparable coverage below 80%, inspect phase gaps')
        if coverage < .8:
            result['unsupported'].append(name + ': comparable sample coverage below 80%')
        if not usable:
            result['landmarks'][name] = item
            continue
        if len(usable) < 2:
            errors = [math.dist([v*ss for v in r['reference'][name]['xy']], [v*cs for v in r['candidate'][name]['xy']]) for r in usable]
            item['raw'] = stats(errors)
            result['unsupported'].append(name + ': fewer than two comparable temporal samples')
            result['landmarks'][name] = item
            pooled_raw.extend(errors)
            continue
        a = [[v*ss for v in r['reference'][name]['xy']] for r in usable]
        b = [[v*cs for v in r['candidate'][name]['xy']] for r in usable]
        u = [r['reference'][name]['uncertainty_px']*ss+r['candidate'][name]['uncertainty_px']*cs for r in usable]
        am = [statistics.mean(v[k] for v in a) for k in (0, 1)]
        bm = [statistics.mean(v[k] for v in b) for k in (0, 1)]
        raw = [math.dist(x,y) for x,y in zip(a,b)]
        centered = [math.dist([x[k]-am[k] for k in (0,1)], [y[k]-bm[k] for k in (0,1)]) for x,y in zip(a,b)]
        # Center uncertainty includes each point AND the uncertain constant mean.
        centered_u = [v+statistics.mean(u) for v in u]
        item.update(raw=stats(raw), mean_centered=stats(centered), constant_means={'reference': am, 'candidate': bm},
                    centered_uncertainty=interval_stats(centered, centered_u, .06*L if L is not None else None))
        item['amplitudes'] = {}
        for k, axis in enumerate(('x','y')):
            ref = max(v[k] for v in a)-min(v[k] for v in a)
            cand = max(v[k] for v in b)-min(v[k] for v in b)
            err = abs(ref-cand)
            bound = 2*(max(r['reference'][name]['uncertainty_px']*ss for r in usable)+max(r['candidate'][name]['uncertainty_px']*cs for r in usable))
            threshold = max(.2*ref, .02*L) if L is not None else None
            # Reference amplitude uncertainty also changes a relative tolerance.
            ref_u = 2*max(r['reference'][name]['uncertainty_px']*ss for r in usable)
            low_tol = max(.2*max(0,ref-ref_u),.02*L) if L is not None else None
            high_tol = max(.2*(ref+ref_u),.02*L) if L is not None else None
            state = 'unsupported' if L is None else 'within_threshold' if err+bound < low_tol else 'outside_threshold' if max(0,err-bound) > high_tol else 'inconclusive'
            item['amplitudes'][axis] = {'reference_px': ref, 'candidate_px': cand, 'error_px': err,
                 'error_bound_px': bound, 'threshold_px': threshold, 'threshold_interval_px': [low_tol,high_tol], 'threshold_state': state}
        ba = baseline_row['reference'][name]; bb = baseline_row['candidate'][name]
        if ba['state'] == bb['state'] == 'visible':
            refbase = [v*ss for v in ba['xy']]; candbase = [v*cs for v in bb['xy']]
            delta = [[(y[k]-candbase[k])-(x[k]-refbase[k]) for k in (0,1)] for x,y in zip(a,b)]
            item['fixed_baseline_displacement'] = {'baseline_frame': doc['baseline_frame'], 'error': stats([math.hypot(*v) for v in delta]),
                                                 'residual_xy_px': delta, 'frames': [r['frame'] for r in usable],
                                                 'annotation_error_bound_px': [v+ba['uncertainty_px']*ss+bb['uncertainty_px']*cs for v in u]}
        else:
            result['unsupported'].append(name + ': pre-event baseline not observable')
        item['trace'] = [{'frame': r['frame'], 'source_pts': r['source_pts'], 'candidate_time': r['candidate_time'],
                          'raw_error_px': e, 'centered_error_px': ce, 'annotation_error_bound_px': unc}
                         for r,e,ce,unc in zip(usable, raw, centered, centered_u)]
        worst.extend({'frame': r['frame'], 'landmark': name, 'raw_error_px': e} for r,e in zip(usable,raw))
        pooled_raw.extend(raw); pooled_centered.extend(centered); pooled_uncertainty.extend(centered_u)
        result['landmarks'][name] = item
    result['aggregate'] = {'raw': stats(pooled_raw), 'mean_centered': stats(pooled_centered),
        'centered_uncertainty': interval_stats(pooled_centered, pooled_uncertainty, .06*L if L is not None else None)}
    if L is None:
        result['unsupported'].append('Reference normalization L unavailable; normalized spatial thresholds unsupported')
    result['worst_samples'] = sorted(worst, key=lambda v:v['raw_error_px'], reverse=True)[:24]
    result['axis'] = axis_report(doc, selected)
    result['native_joins'] = joins_report(doc, rows)
    result['third_landmark_geometry'] = third_landmark_report(doc, rows)
    if result['axis'].get('centered_status','').startswith('unsupported'):
        result['unsupported'].append(result['axis']['centered_status'])
    for side, values in result['third_landmark_geometry']['sides'].items():
        if not values or all(v['noncollinearity'] != 'supported' for v in values):
            result['unsupported'].append(side + ': third weapon landmark has no observed noncollinear geometry')
    if result['axis']['degenerate_frames']:
        result['unsupported'].append('Degenerate projected weapon axis on listed frames')
    tb = rational(doc['source']['time_base'], 'time_base')
    by_frame = {r['frame']: r for r in rows}
    for event in doc.get('events', []):
        sr = [by_frame[f] for f in event['source_frame_interval']]
        expected = [rational(r['candidate_time'], 'time') for r in sr]
        cand = event.get('candidate_time_interval')
        item = {'name': event['name'], 'observation': event['observation'], 'source_frame_interval': event['source_frame_interval'],
                'mapped_source_time_interval': [ratio(v) for v in expected], 'candidate_time_interval': cand, 'phase_error_seconds_interval': None}
        if cand is not None:
            c = [rational(v, 'candidate event time') for v in cand]
            item['phase_error_seconds_interval'] = [float(c[0]-expected[1]),float(c[1]-expected[0])]
        else:
            result['unsupported'].append('Candidate event missing: ' + event['name'])
        result['events'].append(item)
    result['native_source_duration_between_samples_seconds'] = ratio((rows[-1]['source_pts']-rows[0]['source_pts'])*tb)
    return result

def coverage_report(rows,name):
    visible=[r for r in rows if r['reference'][name]['state']=='visible']
    valid=[r for r in visible if r['candidate'][name]['state']=='visible']
    gaps=[];start=None;last=None
    for r in rows:
        bad=r['reference'][name]['state']!='visible' or r['candidate'][name]['state']!='visible'
        if bad:
            if start is None:start=r['frame']
            last=r['frame']
        elif start is not None:
            gaps.append([start,last+1]);start=None
    if start is not None:gaps.append([start,last+1])
    return {'planned':len(rows),'source_visible':len(visible),'candidate_valid_when_source_visible':len(valid),
            'source_visible_over_planned':len(visible)/len(rows),
            'candidate_valid_over_source_visible':len(valid)/len(visible) if visible else None,
            'comparable_over_planned':len(valid)/len(rows),'noncomparable_intervals_half_open':gaps}

def axis_report(doc, rows):
    ids = doc['axis_landmarks']; reg = doc['registration']; angles = [[],[]]; side_bounds = [[],[]]; bounds = []; frames = []; degenerate = []
    for r in rows:
        if not all(r[side][n]['state'] == 'visible' for side in ('reference','candidate') for n in ids):
            continue
        local = []; unc = []
        for side in ('reference','candidate'):
            a,b = [r[side][n] for n in ids]
            d = [b['xy'][k]-a['xy'][k] for k in (0,1)]; length = math.hypot(*d)
            u = a['uncertainty_px']+b['uncertainty_px']
            if length <= max(u, 1e-8):
                degenerate.append(r['frame']); break
            local.append(math.degrees(math.atan2(d[1],d[0])))
            unc.append(math.degrees(math.asin(min(1,u/length))))
        if len(local) == 2:
            for i in (0,1):
                angles[i].append(local[i]); side_bounds[i].append(unc[i])
            frames.append(r['frame']); bounds.append(sum(unc))
    report = {'frames':frames,'degenerate_frames':sorted(set(degenerate)), 'raw_error_degrees':None,'centered_error_degrees':None,'coverage':len(frames)/len(rows)}
    if not frames: return report
    if len(frames) < 2:
        report['raw_error_degrees'] = stats([abs(circular_delta(x,y)) for x,y in zip(*angles)])
        report['centered_status']='unsupported: fewer than two comparable temporal samples'
        return report
    raw = [abs(circular_delta(x,y)) for x,y in zip(*angles)]
    report['raw_error_degrees'] = stats(raw)
    branch_risks=[]
    native_by_frame = {r['frame']:r for r in doc['samples']}
    for i in range(1,len(frames)):
        hidden_between = any(any(native_by_frame[f][side][n]['state']!='visible' for side in ('reference','candidate') for n in ids) for f in range(frames[i-1]+1,frames[i]))
        if hidden_between or frames[i]-frames[i-1] != doc['metrics_stride']:
            branch_risks.append({'from_frame':frames[i-1],'to_frame':frames[i],'reason':'visibility gap'})
        for side in (0,1):
            if abs(circular_delta(angles[side][i],angles[side][i-1]))+side_bounds[side][i]+side_bounds[side][i-1] >= 180:
                branch_risks.append({'from_frame':frames[i-1],'to_frame':frames[i],'reason':'uncertainty crosses unwrap branch','side':('reference','candidate')[side]})
    report['unwrap_unsupported_intervals']=branch_risks
    if branch_risks:
        report['centered_status']='unsupported: ambiguous unwrap branch or visibility gap'
        return report
    a,b = map(unwrapped, angles)
    am=statistics.mean(a); bm=statistics.mean(b)
    centered=[abs((x-am)-(y-bm)) for x,y in zip(a,b)]
    amp_a=max(a)-min(a); amp_b=max(b)-min(b); amp_err=abs(amp_a-amp_b)
    report.update(raw_error_degrees=stats(raw),centered_error_degrees=stats(centered),
                  constant_means_degrees=[am,bm],reference_trace_degrees=a,candidate_trace_degrees=b,
                  centered_uncertainty=interval_stats(centered,[u+statistics.mean(bounds) for u in bounds],5),
                  amplitude={'reference_degrees':amp_a,'candidate_degrees':amp_b,'error_degrees':amp_err,
                             'annotation_error_bound_degrees':2*(max(side_bounds[0])+max(side_bounds[1])),'threshold_degrees':max(.2*amp_a,2)},
                  direction_agreement_diagnostic=sum((x-am)*(y-bm) for x,y in zip(a,b)))
    return report

def joins_report(doc, rows):
    # Native adjacent displacement/speed; no invented continuity points or loop wrap.
    output={}; tb=rational(doc['source']['time_base'],'time_base')
    for name in (p['id'] for p in doc['landmarks']):
        sides={}
        for side,scale in (('reference',doc['registration']['source_scale']),('candidate',doc['registration']['candidate_scale'])):
            values=[]
            for a,b in zip(rows,rows[1:]):
                if a[side][name]['state']==b[side][name]['state']=='visible':
                    d=math.dist(a[side][name]['xy'],b[side][name]['xy'])*scale
                    dt=float((b['source_pts']-a['source_pts'])*tb)
                    bound=(a[side][name]['uncertainty_px']+b[side][name]['uncertainty_px'])*scale
                    values.append({'from_frame':a['frame'],'to_frame':b['frame'],'displacement_px':d,'speed_px_s':d/dt,'annotation_displacement_bound_px':bound,'annotation_speed_bound_px_s':bound/dt})
            sides[side]={'largest_steps':sorted(values,key=lambda r:r['displacement_px'],reverse=True)[:12],
                         'largest_speeds':sorted(values,key=lambda r:r['speed_px_s'],reverse=True)[:12],
                         'observed_adjacent_pairs':len(values),'planned_adjacent_pairs':len(rows)-1,
                         'step_stats':stats([v['displacement_px'] for v in values]), 'speed_stats':stats([v['speed_px_s'] for v in values])}
        output[name]=sides
    return output

def third_landmark_report(doc, rows):
    names=[p['id'] for p in doc['landmarks']]; a,b=doc['axis_landmarks']; third=next(n for n in names if n not in (a,b))
    result={'third_landmark':third,'scope':'Signed screen triangle area is a direction/degeneracy witness, not 3D orientation proof.','sides':{}}
    for side in ('reference','candidate'):
        areas=[]
        for r in rows:
            if all(r[side][n]['state']=='visible' for n in (a,b,third)):
                p,q,t=[r[side][n]['xy'] for n in (a,b,third)]
                area=(q[0]-p[0])*(t[1]-p[1])-(q[1]-p[1])*(t[0]-p[0])
                up,uq,ut=[r[side][n]['uncertainty_px'] for n in (a,b,third)]
                du=up+uq;dv=up+ut
                area_bound=du*math.dist(t,p)+dv*math.dist(q,p)+du*dv
                areas.append({'frame':r['frame'],'signed_double_area_px2':area,'annotation_area_bound_px2':area_bound,'noncollinearity':'supported' if abs(area)>area_bound else 'inconclusive'})
        result['sides'][side]=areas
    return result

def plot_report(report, output):
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    for name,item in report['landmarks'].items():
        trace=item.get('trace',[])
        if not trace: continue
        axes[0].plot([r['frame'] for r in trace],[r['raw_error_px'] for r in trace],label=name)
        axes[1].plot([r['frame'] for r in trace],[r['centered_error_px'] for r in trace],label=name)
    axes[0].set_ylabel('Raw error, pixels'); axes[1].set_ylabel('Mean-centered error, pixels'); axes[1].set_xlabel('Exact source frame')
    if report['normalization']['L_px'] is not None:
        axes[1].axhline(.06*report['normalization']['L_px'],color='black',linestyle='--',label='0.06 L diagnostic limit')
    for ax in axes: ax.legend()
    fig.suptitle(report['action']+' / diagnostic only / no score'); fig.tight_layout(); fig.savefig(output,dpi=130); plt.close(fig)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--plot',action='store_true'); parser.add_argument('--pts-map',type=Path)
    args=parser.parse_args(); blob=args.input.read_bytes(); doc=strict_json(blob); result=compare(doc,decoded_pts=args.pts_map.read_bytes() if args.pts_map else None)
    result['input_file_sha256']=sha256(blob)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if args.plot: plot_report(result,args.output/'residuals.png')
    print(json.dumps({'status':result['status'],'action':result['action'],'score':result['score'],'hard_gate_findings':len(result['hard_gate_findings']),'output':str(args.output)}))

if __name__=='__main__': main()
