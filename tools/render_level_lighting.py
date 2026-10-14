"""Review actual baked geometry. These CPU renders are not DX12 captures."""
from pathlib import Path
from render_city import load,render
root=Path(__file__).resolve().parents[1]
for level,views in [('range', [('overview',[20,15,14],[0,0,-18]),('spawn',[0,1.7,8],[0,1,-15])]),('cedar_junction',[('street',[1,1.8,39],[0,3,-10]),('interior',[-43,1.82,-49],[-48,1.4,-43]),('upstairs',[-40,5.15,-43.5],[-48,4.4,-46])])]:
 folder=root/'assets/levels'/level;out=folder/'lighting_review';out.mkdir(exist_ok=True)
 v,f=load(folder/'lighting.bin')
 for name,eye,target in views:
  render(v,f,eye,target,out/(name+'.jpg'),level+' / '+name+' / baked lighting',baked=True)
