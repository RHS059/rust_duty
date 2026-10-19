import hashlib,json
from pathlib import Path
HERE=Path(__file__).absolute().parent
def verify():
 pins=json.loads((HERE/'PINS.json').read_bytes());actual={x.name for x in HERE.iterdir() if x.is_file()}
 assert actual==set(pins)|{'PINS.json'}
 for n,h in pins.items():assert Path(n).name==n and hashlib.sha256((HERE/n).read_bytes()).hexdigest()==h,n
 return {'files':len(actual),'pins_sha256':hashlib.sha256((HERE/'PINS.json').read_bytes()).hexdigest()}
if __name__=='__main__':print(json.dumps(verify()))
