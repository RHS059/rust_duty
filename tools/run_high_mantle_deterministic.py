#!/usr/bin/env python3
"""Native-owner-only bounded 60/30 Hz ordinary-Input complement; dry by default.

Same private authenticated Xvfb route as platform-input capture. No build, asset
copy, binding activation, physics manipulation or source/blend retiming.
"""
import argparse,json,os,shutil,subprocess,time
from pathlib import Path
from run_high_mantle_inputs import FLOOR,PER_SCENARIO,WALL_SECONDS,bound_child_files,require_native_platform,verified_config as platform_config,read_trace_terminal
from verify_high_mantle_observer import need,sha,read,safe_path,near
from verify_high_mantle_deterministic import RETURN_SECONDS

def verified_config(path,expected):
    c,root,identity=platform_config(path,expected)
    need(near(c['binding']['return_seconds'],RETURN_SECONDS,1e-8),'fixed fixture requires independently approved0.20s return')
    for script in ('run_high_mantle_deterministic.py','verify_high_mantle_deterministic.py','verify_high_mantle_deterministic_run.py'):
        key=str((Path(__file__).resolve().parent/script).relative_to(root))
        need(key in c['inputs_sha256'],'deterministic source must be independently pinned: '+script)
    for suffix in ('src/app.rs','src/traversal_replay.rs','src/high_mantle_capture.rs','src/high_mantle_observer.rs'):
        need(any(name.endswith('/'+suffix) for name in c['source_paths']),'missing deterministic source pin: '+suffix)
    return c,root,identity

def invocation(exe,manifest,output,identity,hz):
    need(hz in (30,60),'invalid rate')
    return [str(exe),'--renderer=gl','--level=range','--hold-controls','--no-update',
            f'--animation-manifest={manifest}',f'--onehand-observer={output}',f'--onehand-witness={identity}',
            '--onehand-deterministic','--capture-sequence=gameplay-high-onto',f'--capture-hz={hz}',
            '--capture-native-window']

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--config-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hz',type=int,choices=[30,60],action='append');p.add_argument('--execute',action='store_true')
    a=p.parse_args();c,root,identity=verified_config(a.config,a.config_sha256)
    rates=a.hz or [60,30];need(len(rates)==len(set(rates)),'duplicate rate')
    output=a.output.resolve();need(not output.exists(),'output must be new')
    required=FLOOR+len(rates)*PER_SCENARIO+32*1024**2
    need(shutil.disk_usage(output.parent).free>=required,'insufficient disk budget preserving1GiB')
    commands={str(hz):invocation(safe_path(root,c['executable']),safe_path(root,c['manifest']),output/str(hz)/'game',identity,hz) for hz in rates}
    plan={'schema':'rust-duty-onehand-deterministic-run/v1','config_sha256':a.config_sha256,
          'frame_witness':identity,'native_platform':'Linux','windows_dx12_verified':False,
          'input_route':'deterministic_ordinary_input','real_platform_hotkeys':False,
          'disk_floor_bytes':FLOOR,'per_rate_max_bytes':PER_SCENARIO,'wall_seconds_bound_per_rate':WALL_SECONDS,
          'nominal_sequence_seconds':2.7,'max_committed_ticks':324,'commands':commands,'runs':[]}
    if not a.execute:print(json.dumps(plan,indent=2));return 0
    require_native_platform()
    from platform_x11_input import Input
    display=':97';need(not Path('/tmp/.X11-unix/X97').exists() and not Path('/tmp/.X97-lock').exists(),'display97 already owned')
    output.mkdir(mode=0o700);auth=output/'xauthority';auth.touch(mode=0o600)
    subprocess.run(['xauth','-f',str(auth),'add',display,'MIT-MAGIC-COOKIE-1',os.urandom(16).hex()],check=True,stdout=subprocess.DEVNULL)
    env=dict(os.environ,DISPLAY=display,XAUTHORITY=str(auth),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',LP_NUM_THREADS='2',OMP_NUM_THREADS='2')
    previous=os.environ.get('XAUTHORITY');os.environ['XAUTHORITY']=str(auth)
    server=None;game=None;keys=None
    def save():(output/'run.json').write_text(json.dumps(plan,indent=2)+'\n')
    save()
    try:
        with (output/'xvfb.log').open('x') as log:
            server=subprocess.Popen([str(safe_path(root,c['xvfb'])),display,'-screen','0','1440x900x24','-nolisten','tcp','-auth',str(auth),'-fp','built-ins','-noreset'],env=env,stdout=log,stderr=subprocess.STDOUT,preexec_fn=bound_child_files)
            deadline=time.monotonic()+10
            while not Path('/tmp/.X11-unix/X97').exists():
                need(server.poll() is None and time.monotonic()<deadline,'private X server failed');time.sleep(.05)
            keys=Input(display)
            for hz in rates:
                folder=output/str(hz);folder.mkdir();entry={'hz':hz,'command':commands[str(hz)]};plan['runs'].append(entry);save()
                with (folder/'game.log').open('x') as glog:
                    began=time.monotonic();focused=False
                    game=subprocess.Popen(entry['command'],cwd=safe_path(root,c['working_directory']),env=env,stdout=glog,stderr=subprocess.STDOUT,preexec_fn=bound_child_files)
                    while game.poll() is None:
                        need(time.monotonic()-began<WALL_SECONDS,'600-second rate safety bound reached')
                        need(shutil.disk_usage(output).free>=FLOOR+16*1024**2,'disk reserve reached; stop capture')
                        need(server.poll() is None,'private X server exited')
                        if not focused:
                            windows=keys.windows();need(len(windows)<=1,'ambiguous private app window')
                            if windows:keys.focus(windows[0]);focused=True
                        time.sleep(.05)
                    entry['exit_code']=game.returncode;entry['wall_seconds']=time.monotonic()-began
                    need(game.returncode==0 and focused,'app failed or no native window observed')
                    need(read_trace_terminal(folder/'game'/'observer.jsonl'),'observer not terminal')
                    entry['completed']=True;save();game=None
            verified_config(a.config,a.config_sha256)
            plan['inputs_unchanged']=True;plan['capture_processes_completed']=True;save()
    except BaseException as e:
        plan['error']=str(e);plan['capture_processes_completed']=False;save();raise
    finally:
        if game and game.poll() is None:
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
        if previous is None:os.environ.pop('XAUTHORITY',None)
        else:os.environ['XAUTHORITY']=previous
    return 0
if __name__=='__main__':raise SystemExit(main())
