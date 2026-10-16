"""Independent ordinary-key recipe. No native execution and no simulation writer."""
import copy
KEYS=('W','D','Space','Escape','Enter','F2','F9')
CASES=('pause','reset','debug-death')

def blank_edges():
    return dict(keys=[dict(key=k,down=False,pressed=False,released=False) for k in KEYS],
        right_mouse=dict(down=False,pressed=False,released=False),movement=[0.,0.],mouse_delta=[0.,0.])

class Recipe:
    def __init__(self,case):
        self.case=case;self.stage='Baseline';self.held=set();self.ads=False
        self.request=False;self.paused=0;self.cleared=0;self.began=0.
    def next(self,s,active):
        e=blank_edges();old=set(self.held);old_ads=self.ads;t=s['simulation_time'];h=s['high'];p=self.stage
        assert 0<=t<=8
        if p=='Baseline':
            assert active and t==0;self.stage='Request'
        elif p=='Request':
            assert active and not s['dead']
            if h:self.held.discard('W');self.stage='Native'
            elif not self.request:self.held.add('W');self.tap(e,'Space');self.request=True
            else:assert t<=.5
        elif p=='Native':
            assert active and h and h['outgoing'] is None and not s['dead']
            if h['seconds']>=.45:
                assert h['seconds']<.80
                self.tap(e,dict(pause='Escape',reset='F2',**{'debug-death':'F9'})[self.case])
                self.stage='Paused' if self.case=='pause' else 'Cleared'
        elif p=='Paused':
            assert not active and h and h['outgoing'] and s['mantle'] is None
            self.paused+=1
            if self.paused==3:self.tap(e,'Enter');self.stage='Resume'
        elif p=='Resume':
            assert active and h
            self.began=t;self.stage='Tail';self.held.add('D');self.ads=True
        elif p=='Tail':
            assert active and not s['dead']
            if t-self.began>=.75:
                assert h is None and s['mantle'] is None;self.stage='Done'
        elif p=='Cleared':
            assert h is None and s['mantle'] is None and active and s['dead']==(self.case=='debug-death')
            self.cleared+=1
            if self.cleared>=3:self.stage='Done'
        else:raise AssertionError('input after done')
        for key in e['keys']:
            k=key['key'];key['down']=k in self.held
            key['pressed']|=k in self.held-old;key['released']|=k in old-self.held
        e['right_mouse']=dict(down=self.ads,pressed=self.ads and not old_ads,released=old_ads and not self.ads)
        e['movement']=[float('D' in self.held),float('W' in self.held)]
        return e
    def tap(self,e,key):
        k=next(k for k in e['keys'] if k['key']==key);k['pressed']=k['released']=True

def pressed(e,key):return next(k['pressed'] for k in e['keys'] if k['key']==key)
def input_value(e,jump=False,cleared=False):
    return dict(movement=[0.,0.] if cleared else e['movement'],jump=jump,reload=False,
        ads=False if cleared else e['right_mouse']['down'],fire=False,crouch=False,prone=False,
        sprint=False,tactical_sprint=False,mount=False,sidearm=False,lean=0.,cant=False)

def selected_marker(s,active,stage,case,seen):
    h=s['high'];out=h and h['outgoing']
    if h and not out and h['seconds']>=.25 and 'native' not in seen:return 'native'
    if case=='pause':
        if not active and h and 'paused' not in seen:return 'paused'
        if out and 0<out['weight']<.5 and 'tail_early' not in seen:return 'tail_early'
        if out and .5<=out['weight']<1 and 'tail_late' not in seen:return 'tail_late'
        if not h and 'paused' in seen and 'clear' not in seen:return 'clear'
        if not h and 'clear' in seen and 'ads' not in seen and s['visual']['visual_ads']>.95:return 'ads'
    else:
        if not h and 'native' in seen and 'after' not in seen:return 'after'
        if stage=='Done' and 'terminal' not in seen:return 'terminal'
    return None
