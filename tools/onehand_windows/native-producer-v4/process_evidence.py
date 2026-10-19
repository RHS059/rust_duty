"""Read-only semantic reconstruction of reviewed v2 process evidence.

Hash consistency alone is insufficient. These checks bind all retained records
and sampled resources to externally admitted expectations. They do not attest a
host, establish continuous memory coverage, or guarantee scheduler latency.
"""
import json,math
from pathlib import Path
from pinned_code import file_sha,require

BASE=('schema','command','cwd','host_binding','limits','supervisor_python','started_unix','clock','memory_scope','proof_scope')
START=('state','pid','backend','executable_before','initial_available_bytes','initial_free_bytes','attempt')
RESULT=('state','completed','started','pid','exit_code','signal','timed_out','resource_stop_reason','error_type','finished_unix','duration_seconds','process_duration_seconds','peak_sampled_rss_bytes','rss_ceiling_bytes','sample_count','rows','consumer_complete','cleanup_complete','constructor_cleanup_complete','windows_job_empty_verified','parent_already_in_windows_job','executable_before','executable_after','streams','queue_peak_bytes','queue_peak_rows','attempt','started_record','transport_record')
HOST=('runner_id','run_id','build_sha256','context_sha256','observed_host','environment_sha256','environment_keys','owner_lock')
IDENTITY=('path','sha256','bytes','device','inode','mtime_ns')


def exact(actual,expected,label):
    require(json.dumps(actual,sort_keys=True,allow_nan=False,separators=(',',':'))==json.dumps(expected,sort_keys=True,allow_nan=False,separators=(',',':')),label+' differs')


def keys(value,fields,label):
    require(type(value) is dict and set(value)==set(fields),label+' fields differ')


def number(value,label):
    require(type(value) in (int,float) and math.isfinite(value),label+' must be finite');return value


def integer(value,minimum,maximum,label):
    require(type(value) is int and minimum<=value<=maximum,label+' outside bound');return value


def sha(value):
    require(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value),'invalid SHA256');return value


def read_json(adapter,path,cap):
    require(path.stat().st_size<=cap,'process JSON exceeds cap')
    value=json.loads(path.read_bytes(),parse_constant=adapter.reject_constant,object_pairs_hook=adapter.unique_object)
    adapter.validate_json(value);return value


def identity(value,expected,label):
    keys(value,IDENTITY,label)
    for key in ('path','sha256'):exact(value[key],expected[key],label+' '+key)
    sha(value['sha256'])
    for key in ('bytes','device','inode','mtime_ns'):integer(value[key],0,2**128,label+' '+key)
    require(value['bytes']>0,label+' empty executable')
    if 'bytes' in expected:exact(value['bytes'],expected['bytes'],label+' bytes')


def verify_completed_process(adapter,root,expected):
    """Return verified terminal + recomputed sampled-resource summary.

    The caller pins terminal.json externally before calling. expected contains
    command, cwd, host_binding, limits, supervisor_python, executable and rows.
    Full receipts/streams must remain present even when private source rows have
    been independently retired. No self-asserted completion field is sufficient.
    """
    keys(expected,('command','cwd','host_binding','limits','supervisor_python','executable','rows'),'process expectations')
    root=Path(root)
    proc=adapter.verify_attempt(root,require_completed=True)
    limits=adapter.Limits(**expected['limits']).validate()
    keys(proc,(*BASE,*RESULT),'terminal')
    records={name:read_json(adapter,root/(name+'.json'),limits.max_receipt_bytes) for name in ('attempt','started','transport')}
    attempt,started,transport=(records[n] for n in ('attempt','started','transport'))
    keys(attempt,(*BASE,'state'),'attempt');keys(started,(*BASE,*START),'started');keys(transport,(*BASE,*RESULT),'transport')
    exact(attempt['state'],'prepared','attempt state');exact(started['state'],'started','started state')
    exact(started['backend'],'windows-job-list-overlapped-v2','native process backend')
    exact(transport['state'],'transport_stopped','transport state');exact(proc['state'],'completed','terminal state')
    for key in ('command','cwd','host_binding','limits','rows'):exact(proc[key],expected[key],'process '+key)
    keys(proc['host_binding'],HOST,'host binding');sha(proc['host_binding']['environment_sha256'])
    envkeys=proc['host_binding']['environment_keys']
    require(type(envkeys) is list and len(envkeys)<=256 and all(type(k) is str and k and '=' not in k and '\0' not in k for k in envkeys),'environment keys invalid')
    require(envkeys==sorted(set(envkeys)) and len({k.upper() for k in envkeys})==len(envkeys),'environment keys ambiguous')
    require('SYSTEMROOT' in {k.upper() for k in envkeys},'Windows environment SystemRoot required')
    exact(proc['schema'],'rust-duty-owned-process/v1','process schema')
    exact(proc['clock'],'time.monotonic; elapsed not derived from wall clock','clock scope')
    exact(proc['memory_scope'],'sampled own direct child RSS / Windows working set; not instantaneous peak or commit guarantee','memory scope')
    exact(proc['proof_scope'],'transport only; no numerical/candidate/Windows-production admission','transport scope')
    identity(proc['supervisor_python'],expected['supervisor_python'],'supervisor Python')
    identity(proc['executable_before'],expected['executable'],'native executable')
    exact(proc['executable_after'],proc['executable_before'],'native executable stability')
    for name,stream in proc['streams'].items():
        keys(stream,('path','sha256','bytes','observed_bytes','observed_sha256','eof_observed','truncated','scope'),'retained '+name+' stream')
        exact(stream['scope'],'exact retained bytes; no claim about unread bytes','retained stream scope')
    for name,record in records.items():
        for key in BASE:exact(record[key],proc[key],name+' '+key)
    for name,record in (('started',started),('transport',transport)):
        exact(record['pid'],proc['pid'],name+' child PID')
        exact(record['executable_before'],proc['executable_before'],name+' executable')
    integer(proc['pid'],1,2**32-1,'child PID')
    require(number(proc['started_unix'],'start wall clock')>0,'invalid start wall clock')
    initial_available=integer(started['initial_available_bytes'],limits.initial_available_bytes,2**128,'initial available memory')
    initial_free=integer(started['initial_free_bytes'],limits.disk_floor_bytes+limits.retained_budget,2**128,'initial disk retention reserve')
    def reference(name):
        path=root/(name+'.json')
        return {'path':path.name,'bytes':path.stat().st_size,'sha256':file_sha(path)}
    for record in (started,transport,proc):exact(record['attempt'],reference('attempt'),'attempt predecessor')
    for record in (transport,proc):exact(record['started_record'],reference('started'),'started predecessor')
    exact(transport['transport_record'],None,'transport predecessor must not self-reference')
    exact(proc['transport_record'],reference('transport'),'terminal transport predecessor')
    # All process/resource evidence is final at transport stop. Consumer rows and
    # terminal elapsed time may advance while the bounded pipe queue is consumed.
    for key in ('started','pid','exit_code','signal','timed_out','resource_stop_reason','error_type','process_duration_seconds','peak_sampled_rss_bytes','rss_ceiling_bytes','sample_count','cleanup_complete','constructor_cleanup_complete','windows_job_empty_verified','parent_already_in_windows_job','executable_before','executable_after','streams','queue_peak_bytes','queue_peak_rows'):
        exact(transport[key],proc[key],'transport/terminal '+key)
    for record in (transport,proc):
        for key,want in {'started':True,'exit_code':0,'signal':None,'timed_out':False,'resource_stop_reason':None,'error_type':None,'cleanup_complete':True,'constructor_cleanup_complete':None,'windows_job_empty_verified':True,'rss_ceiling_bytes':limits.rss_bytes}.items():exact(record[key],want,'successful process '+key)
        require(type(record['parent_already_in_windows_job']) is bool,'parent job observation required')
        number(record['finished_unix'],'finish wall clock')
        require(0<=number(record['duration_seconds'],'duration')<limits.deadline_seconds,'process duration deadline')
    exact(transport['completed'],False,'transport stop is not terminal completion')
    require(type(transport['consumer_complete']) is bool,'transport consumer state invalid')
    exact(proc['completed'],True,'terminal complete');exact(proc['consumer_complete'],True,'terminal consumer complete')
    integer(transport['rows'],0,proc['rows'],'transport consumed rows')
    integer(proc['rows'],0,limits.max_rows,'terminal consumed rows')
    integer(proc['queue_peak_bytes'],0,limits.queue_bytes,'queue peak bytes');integer(proc['queue_peak_rows'],0,limits.queue_rows,'queue peak rows')
    duration=number(proc['process_duration_seconds'],'native process duration')
    require(0<=duration<=transport['duration_seconds']<=proc['duration_seconds']<limits.deadline_seconds,'process/transport/terminal clock coverage differs')
    count=integer(proc['sample_count'],1,limits.max_samples,'sample count')
    sample_file=root/'samples.jsonl';require(sample_file.stat().st_size<=limits.max_samples_bytes,'resource stream cap')
    samples=[]
    with sample_file.open('rb') as f:
        while True:
            line=f.readline(4097)
            if not line:break
            require(len(line)<=4096 and line.endswith(b'\n'),'bounded complete resource row required')
            row=json.loads(line,parse_constant=adapter.reject_constant,object_pairs_hook=adapter.unique_object);adapter.validate_json(row)
            keys(row,('elapsed_seconds','rss_bytes','mem_available_bytes','free_bytes'),'resource sample')
            require(len(samples)<limits.max_samples,'resource sample count cap');samples.append(row)
    require(len(samples)==count,'actual sample count differs')
    previous=0.;rss_values=[];elapsed_values=[];free_values=[];max_gap=0.;exited=False
    for row in samples:
        elapsed=number(row['elapsed_seconds'],'resource sample clock')
        require(previous<=elapsed<=duration and elapsed<limits.deadline_seconds,'resource clock order/deadline/coverage differs')
        max_gap=max(max_gap,elapsed-previous);previous=elapsed;elapsed_values.append(elapsed)
        rss=row['rss_bytes']
        if rss is None:exited=True
        else:
            require(not exited,'RSS observation after exited-child sample')
            rss_values.append(integer(rss,0,limits.rss_bytes,'sampled child RSS'))
        integer(row['mem_available_bytes'],0,2**128,'available memory sample')
        free_values.append(integer(row['free_bytes'],limits.disk_floor_bytes,2**128,'sampled disk floor'))
    require(rss_values,'actual child RSS observations required')
    exact(proc['peak_sampled_rss_bytes'],max(rss_values),'recomputed peak RSS')
    max_gap=max(max_gap,duration-previous)
    return {'record':proc,'resources':{'sample_count':count,'rss_observation_count':len(rss_values),'first_elapsed_seconds':elapsed_values[0],
        'last_elapsed_seconds':elapsed_values[-1],'process_duration_seconds':duration,'terminal_duration_seconds':proc['duration_seconds'],
        'requested_sample_period_seconds':limits.sample_seconds,'maximum_observed_gap_including_edges_seconds':max_gap,
        'observed_gap_exceeds_requested_period':max_gap>limits.sample_seconds,'peak_sampled_rss_bytes':max(rss_values),
        'minimum_sampled_free_bytes':min(free_values),'initial_available_bytes':initial_available,'initial_free_bytes':initial_free,
        'scope':'sampled direct child RSS and disk only; scheduling gaps are observed, not a continuous-memory or real-time guarantee'}}
