#!/usr/bin/env python3
"""Native-owner-only Xvfb/app-input fixture. Dry plan unless --execute is supplied.

Never build, edit a manifest, fill runtime pins, mutate simulation, call Blender,
upload or publish. Native proof/payload admission/build are separate prerequisites.
Every fixture run starts at the ordinary range spawn. All driving uses XTest.
"""
import argparse, hashlib, json, math, os, shutil, subprocess, sys, time
try:
    import resource
except ImportError:
    resource = None
from pathlib import Path
from verify_high_mantle_observer import read, sha, safe_path, need

FLOOR=1024**3
# RGBA1440x900 + PNG/zlib overhead, 12 PNGs +16MiB journal per scenario.
PER_SCENARIO=12*5_500_000+32*1024**2+2*1024**2
SCENARIOS=('complete','cancel','reset','debug-death')
WALL_SECONDS=600
SIMULATED_SECONDS=30

def bound_child_files():
    # Per-file hard limit also bounds unexpected app/Xvfb log growth.
    require_native_platform()
    resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024**2,16*1024**2))

def require_native_platform():
    need(sys.platform.startswith('linux') and resource is not None,
         'native Xvfb execution requires Linux resource limits; source-only verification is portable')

def invocation(executable,manifest,output,identity):
    return [str(executable),'--renderer=gl','--level=range','--hold-controls','--no-update',
            f'--animation-manifest={manifest}',f'--onehand-observer={output}',f'--onehand-witness={identity}']

def verified_config(path,expected):
    need(sha(path)==expected,'configuration differs from independent expected hash')
    c=read(path);need(c['schema']=='rust-duty-onehand-native-owner-config/v1','wrong config schema')
    root=Path(c['root']).resolve();pins=c['inputs_sha256']
    need(pins and c['all_grid_proof'] in pins,'full proof must be independently pinned')
    for name,digest in pins.items():need(sha(safe_path(root,name))==digest,'input changed: '+name)
    for key in ('executable','manifest','xvfb'):
        need(c[key] in pins,'missing executable/manifest/Xvfb pin')
    need(c['source_paths'] and all(name in pins for name in c['source_paths']),'missing tested source pins')
    need(c['runtime_paths'] and all(name in pins for name in c['runtime_paths']),'missing runtime companion pins')
    for script in ('run_high_mantle_inputs.py','platform_x11_input.py','verify_high_mantle_observer.py','verify_high_mantle_run.py'):
        key=str((Path(__file__).resolve().parent/script).relative_to(root))
        need(key in pins,'fixture/verifier source must be independently pinned: '+script)
    need(c['binding']['return_seconds']>=.05 and c['binding']['return_seconds']<=1.,'invalid expected return')
    # This records the caller's independent reviewed inputs; it does not enable
    # bindings or treat this JSON as a substitute for executable admission.
    identity=hashlib.sha256(json.dumps({'config_sha256':expected,'inputs_sha256':pins},sort_keys=True).encode()).hexdigest()
    return c,root,identity

class Driver:
    def __init__(self,process,folder,keys,output):
        self.process=process;self.folder=folder;self.keys=keys;self.rows=[];self.offset=0;self.buffer=b''
        self.started=time.monotonic();self.log=(output/'platform-inputs.jsonl').open('x');self.commands=0;self.simulated=0.
    def poll(self):
        need(time.monotonic()-self.started<WALL_SECONDS,'600-second scenario safety bound reached')
        need(shutil.disk_usage(self.folder.parent).free>=FLOOR+16*1024**2,'disk reserve reached; stop capture')
        need(self.process.poll() is None,'app exited before scenario terminal observation')
        path=self.folder/'observer.jsonl'
        if path.exists():
            with path.open('rb') as f:f.seek(self.offset);data=f.read();self.offset=f.tell()
            self.buffer+=data
            lines=self.buffer.split(b'\n');self.buffer=lines.pop()
            new=[json.loads(line) for line in lines if line]
            self.simulated += sum(r['simulation_time']-r['step_started'] for r in new if r['kind']=='step')
            need(self.simulated<=SIMULATED_SECONDS,'30 simulated-second scenario bound reached')
            self.rows += new
        return next((r for r in reversed(self.rows) if r['kind']=='frame'),None)
    def wait(self,predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.poll()
            if predicate():return
            time.sleep(.015)
        raise RuntimeError('native input condition timed out')
    def command(self,kind,name,down):
        self.commands+=1;need(self.commands<=4096,'native command bound exceeded')
        self.log.write(json.dumps({'wall_seconds':time.monotonic()-self.started,'kind':kind,'name':name,'down':down})+'\n');self.log.flush()
        if kind=='key':self.keys.key(name,down)
        elif kind=='mouse':self.keys.ads(down)
        else:self.keys.look(int(name))
    def press(self,name):
        self.command('key',name,True);time.sleep(.08);self.command('key',name,False)
    def latest(self):return next((r for r in reversed(self.rows) if r['kind']=='frame'),None)
    def move_axis(self,axis,target,tolerance=.30):
        # Closed-loop key input, not a simulation assignment. Release/brake using
        # observed ordinary velocity, and fail if the narrow lane is not settled.
        deadline=time.monotonic()+120;held=None;last_frame=-1
        while time.monotonic()<deadline:
            r=self.poll()
            if not r or r['app_frame']==last_frame:time.sleep(.01);continue
            last_frame=r['app_frame'];error=target-r['position'][axis];velocity=r['velocity'][axis]
            need(r['app_active'] and r['grounded'] and not r['dead'] and r['high'] is None,'route lost ordinary grounded input')
            if abs(error)<tolerance and abs(velocity)<.09:
                if held:self.command('key',held,False)
                return
            # Receding braking estimate; no fixed wait assumes a render speed.
            correction=error-velocity*.10
            desired=None if abs(correction)<tolerance else ({0:('a','d'),2:('w','s')}[axis][correction>0])
            if desired!=held:
                if held:self.command('key',held,False)
                if desired:self.command('key',desired,True)
                held=desired
        if held:self.command('key',held,False)
        raise RuntimeError('normal-spawn approach did not settle; no teleport fallback')
    def turn_west(self):
        deadline=time.monotonic()+90;last_frame=-1
        while time.monotonic()<deadline:
            r=self.poll()
            if not r or r['app_frame']==last_frame:time.sleep(.015);continue
            last_frame=r['app_frame'];yaw=math.atan2(r['direction'][2],r['direction'][0])
            error=(math.pi-yaw+math.pi)%(2*math.pi)-math.pi
            if abs(error)<math.radians(1):return
            sensitivity=r['look_sensitivity_degrees_per_pixel']
            need(.001<sensitivity<10,'invalid normal look sensitivity')
            dx=max(-120,min(120,round(math.degrees(error)/sensitivity)))
            self.command('look',str(dx),None)
        raise RuntimeError('ordinary mouse turn did not converge; no camera override')
    def approach(self):
        self.wait(lambda:self.latest() is not None)
        r=self.latest();need(r['binding'] is not None,'production high pins remain inactive; stop')
        need(all(abs(x-y)<1e-4 for x,y in zip(r['position'],[0,0,9])),'ordinary range spawn differs')
        if not r['app_active']:self.press('Return');self.wait(lambda:self.latest()['app_active'])
        # Broad east-side lane, then a normal mouse turn. The existing collider
        # settles the final approach even when llvmpipe batches 30 fixed ticks.
        self.move_axis(0,-8.1,.30);self.move_axis(2,-3.,.30)
        self.turn_west()
        self.command('key','w',True)
        self.wait(lambda:abs(self.latest()['position'][0]+8.619)<.06 and self.latest()['speed']<.09)
        r=self.latest();need(abs(r['position'][2]+3.)<.48 and r['grounded'],'east-side high approach missed')
        self.command('key','space',True)
        self.wait(lambda:any(r['kind']=='accepted' and r.get('high') for r in self.rows),30)
        self.command('key','space',False);self.command('mouse','ads',True)
    def scenario(self,name):
        self.approach()
        if name=='complete':
            self.wait(lambda:any(r.get('high') and r['high']['outgoing'] and r['high']['outgoing']['completed'] for r in self.rows))
            endpoint=next(r for r in self.rows if r.get('high') and r['high']['outgoing'] and r['high']['outgoing']['completed'])
            self.wait(lambda:self.latest()['simulation_time']>=endpoint['simulation_time']+.25)
            self.command('key','w',False)
            self.wait(lambda:self.latest()['high'] is None and self.latest()['visual_ads']>.95)
        else:
            self.wait(lambda:self.latest().get('high') and self.latest()['high']['seconds']>=.35)
            self.command('key','w',False);self.command('mouse','ads',False)
            if name=='cancel':
                self.press('Escape');self.wait(lambda:any(r['kind']=='pause_after' for r in self.rows))
                time.sleep(.2);self.press('Escape');self.wait(lambda:self.latest()['app_active'] and self.latest()['high'] is None)
            elif name=='reset':
                self.press('F2');self.wait(lambda:any(r['kind']=='reset_after' for r in self.rows))
            else:
                self.press('F9');self.wait(lambda:any(r['kind']=='debug_death_after' and r['dead'] for r in self.rows))
        # Keep a genuine rendered frame after clearance, then ordinary F10 exit.
        n=self.latest()['app_frame'];self.wait(lambda:self.latest()['app_frame']>n+1)
        self.command('key','w',False);self.command('mouse','ads',False);self.press('F10')
    def close(self):self.log.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--scenario',choices=SCENARIOS,action='append')
    p.add_argument('--execute',action='store_true');a=p.parse_args();c,root,identity=verified_config(a.config,a.config_sha256)
    scenarios=a.scenario or list(SCENARIOS);need(len(set(scenarios))==len(scenarios),'duplicate scenarios')
    output=a.output.resolve();need(not output.exists(),'output must be new')
    required=FLOOR+len(scenarios)*PER_SCENARIO+32*1024**2
    need(shutil.disk_usage(output.parent).free>=required,'insufficient disk budget with1GiB floor')
    exe=safe_path(root,c['executable']);manifest=safe_path(root,c['manifest'])
    plan={'schema':'rust-duty-onehand-native-input-run/v1','config_sha256':a.config_sha256,
          'frame_witness':identity,'native_platform':'Linux','windows_dx12_verified':False,
          'input_route':'XTest to private Xvfb native app','disk_floor_bytes':FLOOR,'per_scenario_max_bytes':PER_SCENARIO,'wall_seconds_bound':WALL_SECONDS,'simulated_seconds_bound':SIMULATED_SECONDS,
          'commands':{s:invocation(exe,manifest,output/s/'game',identity) for s in scenarios},'runs':[]}
    if not a.execute:print(json.dumps(plan,indent=2));return 0
    require_native_platform()
    from platform_x11_input import Input
    display=':97';need(not Path('/tmp/.X11-unix/X97').exists() and not Path('/tmp/.X97-lock').exists(),'display97 already owned')
    output.mkdir(mode=0o700);auth=output/'xauthority';auth.touch(mode=0o600)
    subprocess.run(['xauth','-f',str(auth),'add',display,'MIT-MAGIC-COOKIE-1',os.urandom(16).hex()],check=True,stdout=subprocess.DEVNULL)
    env=dict(os.environ,DISPLAY=display,XAUTHORITY=str(auth),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',LP_NUM_THREADS='2',OMP_NUM_THREADS='2')
    old_auth=os.environ.get('XAUTHORITY');os.environ['XAUTHORITY']=str(auth)
    def save(): (output/'run.json').write_text(json.dumps(plan,indent=2)+'\n')
    save();server=None;game=None;keys=None;driver=None
    try:
        with (output/'xvfb.log').open('x') as log:
            server=subprocess.Popen([str(safe_path(root,c['xvfb'])),display,'-screen','0','1440x900x24','-nolisten','tcp','-auth',str(auth),'-fp','built-ins','-noreset'],env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=bound_child_files)
            deadline=time.monotonic()+10
            while not Path('/tmp/.X11-unix/X97').exists():
                need(server.poll() is None and time.monotonic()<deadline,'private X server failed');time.sleep(.05)
            keys=Input(display)
            for scenario in scenarios:
                folder=output/scenario;folder.mkdir();entry={'scenario':scenario,'command':plan['commands'][scenario]};plan['runs'].append(entry);save()
                with (folder/'game.log').open('x') as glog:
                    game=subprocess.Popen(entry['command'],cwd=safe_path(root,c['working_directory']),env=env,stdout=glog,stderr=subprocess.STDOUT,preexec_fn=bound_child_files)
                    driver=Driver(game,folder/'game',keys,folder)
                    driver.wait(lambda:len(keys.windows())==1);keys.focus(keys.windows()[0])
                    driver.scenario(scenario);game.wait(timeout=20);entry['exit_code']=game.returncode
                    need(game.returncode==0,'app did not exit cleanly');driver.close();driver=None;keys.release()
                    need(read_trace_terminal(folder/'game'/'observer.jsonl'),'observer not terminal')
                    entry['completed']=True;save();game=None
            verified_config(a.config,a.config_sha256)
            plan['inputs_unchanged']=True;plan['capture_processes_completed']=True;save()
    except BaseException as e:
        plan['error']=str(e);plan['capture_processes_completed']=False;save();raise
    finally:
        if driver:driver.close()
        if keys:
            try:keys.release()
            except Exception:pass
        if game and game.poll() is None:
            # Abort this dedicated capture process; never mutate its simulation.
            game.terminate()
            try:game.wait(timeout=10)
            except subprocess.TimeoutExpired:game.kill();game.wait()
        if keys:
            try:keys.close()
            except Exception:pass
        if server:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        auth.unlink(missing_ok=True)
        if old_auth is None:os.environ.pop('XAUTHORITY',None)
        else:os.environ['XAUTHORITY']=old_auth
    return 0

def read_trace_terminal(path):
    last=None
    with path.open() as f:
        for line in f:last=json.loads(line)
    return last is not None and last['kind']=='finished'
if __name__=='__main__':raise SystemExit(main())
