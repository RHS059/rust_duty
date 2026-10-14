"""Source-free r6 envelopes. No key retiming or presentation transforms."""
import math

def smoothstep5(t):
    t = max(0., min(1., t))
    return t*t*t*(10.+t*(-15.+6.*t))

def envelope(keys, frame):
    if frame <= keys[0][0]:
        return float(keys[0][1])
    for (a, va), (b, vb) in zip(keys, keys[1:]):
        if frame <= b:
            return va+(vb-va)*smoothstep5((frame-a)/(b-a))
    return float(keys[-1][1])

def parameters(config, frame):
    names = ('camera_depth_m','camera_pitch_down_deg','camera_roll_deg',
             'weapon_down_pixels','weapon_left_pixels','weapon_pitch_down_deg',
             'weapon_additional_roll_deg','weapon_depth_delta_m')
    return {name: envelope(config[name], frame) for name in names}

def validate_config(c):
    assert c['fps'] == 60 and c['frames'] == [1,69] and c['sample_hz'] == 480
    assert c['reference_source_range_half_open'] == [2241,2310]
    assert c['protected_frames'] == [1,11]
    for name in parameters(c,1):
        keys=c[name]
        assert all(b[0]>a[0] for a,b in zip(keys,keys[1:])), name
        assert keys[0][0]==1 and keys[-1][0]==69, name
        assert all(math.isfinite(x) for pair in keys for x in pair), name
    for i in range(545):
        f=1+i/8;p=parameters(c,f)
        assert 0 <= p['camera_depth_m'] <= 1.31
        assert 0 <= p['camera_pitch_down_deg'] <= 3.01
        assert abs(p['camera_roll_deg']) <= 3.01
        assert abs(p['weapon_additional_roll_deg']) <= 8.01
        assert -0.013 <= p['weapon_depth_delta_m'] <= 0
        if f<=11: assert all(v==0 for v in p.values()), p
        if 35<=f<=45: assert p['camera_depth_m']==1.3
        if f>=45: assert p['camera_roll_deg']==0 and p['weapon_additional_roll_deg']==0
    return True
