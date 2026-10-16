"""Independent, state-driven ordinary Input contract for combined replay v1.

This reads preceding committed state. It never manufactures gameplay state or
claims that a requested traversal was accepted. Keep native/art claims elsewhere.
"""
import math
import struct
DT = struct.unpack('<f', struct.pack('<f', 1/120))[0]
PHASES = ('PrimeShot HighRequest HighRide HighReloadTail ReloadSettle ProneFull '
          'ProneAds Stand SecondShot ProneShort ProneReload ReloadStand EastToLow '
          'SouthLane LowApproach LowRequest LowRide LowAdsTail EastRepeatLow '
          'RepeatLowApproach RepeatLowRequest RepeatLowRide RepeatLowAdsTail '
          'EastToHigh NorthLane HighApproach RepeatHighRequest RepeatHighRide '
          'HighAdsTail Clear Done').split()

class RouteError(ValueError): pass

def blank():
    return dict(movement=[0.,0.], jump=False, ads=False, fire=False, reload=False,
                crouch=False, prone=False, sprint=False, tactical_sprint=False,
                sidearm=False, mount=False, cant=False, lean=0.)

def observed(row):
    high=row.get('high'); low=row.get('low'); prone=row.get('prone_sample')
    return dict(time=row['simulation_time'],position=row['position'],speed=row['speed'],
        grounded=row['grounded'],standing=not row['crouched'] and not row['prone'] and row['stance_progress']>=1,
        mantle=(row.get('mantle') or {}).get('kind'),
        high_completed=bool(high and high.get('outgoing') and high['outgoing']['completed']),
        low_endpoint=bool(low and abs(low['seconds']-63/60)<1e-6),
        prone_seconds=None if not prone else prone['seconds'],prone_return=bool(row.get('prone_return')),
        reload_left=row['reload_left'],ads=row['simulation_ads'],shots=row['shots'],dead=row['dead'])

class Route:
    def __init__(self):
        self.phase='PrimeShot';self.began=0.;self.ticks=0;self.request_at=None;self.counts=[0,0,0]
    def advance(self, phase, s):
        self.phase=phase;self.began=s['time'];self.ticks=0;self.request_at=None
        return self.input(s)
    def input(self,s):
        p=self.phase;t=s['time'];age=t-self.began;i=blank()
        if s['dead'] or not math.isfinite(t) or not all(map(math.isfinite,s['position'])):raise RouteError('death/nonfinite')
        if t>60 or age>12:raise RouteError('timeout')
        if p in ('SouthLane','NorthLane') and s['position'][0]<-8.50:raise RouteError('east lane')
        if p in ('PrimeShot','SecondShot'):
            i['fire']=self.ticks==0;n=1 if p=='PrimeShot' else 2
            if age>=.30 and s['shots']>=n:return self.advance('HighRequest' if p=='PrimeShot' else 'ProneShort',s)
            if age>.5 and s['shots']<n:raise RouteError('priming shot rejected')
        elif p in ('HighRequest','LowRequest','RepeatLowRequest','RepeatHighRequest'):
            high=p in ('HighRequest','RepeatHighRequest');kind='High' if high else 'Low'
            if self.request_at is None:
                if round(t/DT)%4!=2:self.ticks+=1;return i
                if not s['grounded'] or not s['standing'] or s['mantle']:raise RouteError('request support')
                i['movement']=[0.,1.];i['jump']=True;self.request_at=t
            else:
                if s['mantle']!=kind:raise RouteError('traversal rejected')
                self.counts[0 if high else 1]+=1
                return self.advance(dict(HighRequest='HighRide',LowRequest='LowRide',RepeatLowRequest='RepeatLowRide',RepeatHighRequest='RepeatHighRide')[p],s)
        elif p in ('HighRide','LowRide','RepeatLowRide','RepeatHighRide'):
            high=p in ('HighRide','RepeatHighRide');i['ads']=True
            if not s['mantle']:
                if not s['high_completed' if high else 'low_endpoint']:raise RouteError('native endpoint missing')
                return self.advance(dict(HighRide='HighReloadTail',LowRide='LowAdsTail',RepeatLowRide='RepeatLowAdsTail',RepeatHighRide='HighAdsTail')[p],s)
        elif p in ('HighReloadTail','LowAdsTail','RepeatLowAdsTail','HighAdsTail'):
            i['movement']=[0.,1.];i['ads']=p!='HighReloadTail';i['reload']=p=='HighReloadTail' and self.ticks==0
            if p=='HighReloadTail' and self.ticks>1 and s['reload_left']<=0:raise RouteError('high reload rejected')
            if age>=.20:return self.advance(dict(HighReloadTail='ReloadSettle',LowAdsTail='EastRepeatLow',RepeatLowAdsTail='EastToHigh',HighAdsTail='Clear')[p],s)
        elif p in ('ReloadSettle','ReloadStand'):
            if age>=.40 and s['reload_left']<=0 and s['ads']==0 and s['standing'] and s['speed']<.05:
                return self.advance('ProneFull' if p=='ReloadSettle' else 'EastToLow',s)
        elif p in ('ProneFull','ProneShort'):
            i['prone']=True;end=68/60 if p=='ProneFull' else .30
            if s['prone_seconds'] is not None and s['prone_seconds']+1e-6>=end:
                self.counts[2]+=1;return self.advance('ProneAds' if p=='ProneFull' else 'ProneReload',s)
        elif p in ('ProneAds','ProneReload'):
            i['prone']=True;i['ads']=p=='ProneAds';i['reload']=p=='ProneReload' and self.ticks==0
            if self.ticks==1 and not s['prone_return']:raise RouteError('prone return rejected')
            if p=='ProneReload' and self.ticks>1 and s['reload_left']<=0:raise RouteError('prone reload rejected')
            if age>=.35:return self.advance('Stand' if p=='ProneAds' else 'ReloadStand',s)
        elif p=='Stand':
            if age>=.8 and s['standing'] and s['ads']==0 and s['speed']<.05:return self.advance('SecondShot',s)
        elif p in ('EastToLow','EastRepeatLow','EastToHigh'):
            if s['position'][0]<-8.:i['movement']=[0.,-1.]
            elif s['grounded'] and s['speed']<.05 and abs(s['position'][1])<.02:
                return self.advance(dict(EastToLow='SouthLane',EastRepeatLow='RepeatLowApproach',EastToHigh='NorthLane')[p],s)
        elif p in ('SouthLane','NorthLane'):
            delta=(3. if p=='SouthLane' else -3.)-s['position'][2]
            if abs(delta)<.18 and s['speed']<.05 and s['grounded']:return self.advance('LowApproach' if p=='SouthLane' else 'HighApproach',s)
            if abs(delta)>.8 or (s['speed']<.05 and abs(delta)>=.18) or self.ticks%24<3:
                if abs(delta)>=.18:i['movement']=[-math.copysign(1,delta),0.]
        elif p in ('LowApproach','RepeatLowApproach','HighApproach'):
            if s['position'][0]>-8.56:i['movement']=[0.,1.]
            elif s['speed']<.05 and s['grounded'] and s['standing']:
                return self.advance(dict(LowApproach='LowRequest',RepeatLowApproach='RepeatLowRequest',HighApproach='RepeatHighRequest')[p],s)
        elif p=='Clear':
            if age>=.6 and not s['mantle'] and not s['high_completed'] and s['standing'] and s['speed']<.05:
                if self.counts!=[2,2,2]:raise RouteError('counts')
                self.phase='Done';self.began=t;self.ticks=0;self.request_at=None
        elif p!='Done':raise RouteError('unknown phase')
        self.ticks+=1;return i
