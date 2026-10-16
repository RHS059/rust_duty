"""Invented CPU receipts/marker pixels only. No native launch or game/asset proof.
The source-status identity gate is tested separately against actual source pins.
"""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import verify_app_edges as v
from app_edge_synthetic_fixture import make
from test_app_edge_receipts import ReceiptFixture

def marker(p,index,identity,extent=(64,22)):
    image=Image.new('RGBA',extent,(0,0,0,255));pixels=image.load()
    for y in range(2):
        for x in range(64):pixels[x,y]=(255,0,0,255) if x<32 else (0,0,255,255)
    payload=index.to_bytes(4,'little')+(index^0xffffffff).to_bytes(4,'little')+bytes.fromhex(identity)
    for bit in range(320):
        color=(255,255,255,255) if payload[bit//8]&(1<<(bit%8)) else (0,0,0,255)
        x,y=(bit%32)*2,2+(bit//32)*2
        for dy in range(2):
            for dx in range(2):pixels[x+dx,y+dy]=color
    image.save(p)

class NativeFixture:
    def __init__(self,root):
        self.receipts=ReceiptFixture(root);self.c,self.root,self.binary,self.manifest,self.settings=self.receipts.verify()
        self.contract=root/'contract.json';self.pin=v.sha(self.contract)
        self.folder=root/'invented-run';self.folder.mkdir();entries=[]
        for case in v.CASES:
            out=self.folder/case;out.mkdir();identity=v.witness_identity(self.c,case,self.pin);rows=make(case)
            for r in rows:r['binding']=self.c['binding']
            rows[0].update(frame_witness=identity,contract_sha256=self.pin,build_version=self.c['build_version'],build_number=self.c['build_number'])
            journal=out/'observer.jsonl';journal.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows));pins={}
            for r in rows:
                if 'png' not in r:continue
                p=out/r['png'];marker(p,r['capture_index'],identity)
                meta=dict(capture='native window',width=64,height=22,requested='gl',backend='OpenGl',adapter='Invented CPU fixture; never native',
                    frame_witness=dict(schema='rust-duty-capture-frame-witness/v1',frame_index=r['capture_index'],capture_identity=identity))
                Path(str(p)+'.json').write_text(json.dumps(meta));pins[p.name]=v.sha(p);pins[p.name+'.json']=v.sha(str(p)+'.json')
            logs={}
            for stream in ('stdout','stderr'):
                log=out/(stream+'.log');log.write_text('Invented CPU log, no execution.\n' if stream=='stdout' else '')
                logs[stream]=dict(path=case+'/'+log.name,bytes=log.stat().st_size,sha256=v.sha(log))
            entries.append(dict(case=case,command=v.invocation(self.c,self.binary,self.manifest,self.settings,out,case,self.pin),exit_code=0,
                completed=True,timed_out=False,process_group_terminal=True,binary_before_sha256=self.c['binary']['sha256'],binary_after_sha256=self.c['binary']['sha256'],
                wall_seconds=rows[-1]['wall_seconds'],observer_sha256=v.sha(journal),capture_files_sha256=pins,process_logs=logs,
                resource_observation=dict(live_guard_active=True,guard_triggered=False,minimum_free_bytes=1288490189,minimum_memory_available_bytes=2147483648)))
        self.run=dict(schema='rust-duty-app-edge-native-run/v1',contract_sha256=self.pin,completed=True,inputs_unchanged=True,
            source_fingerprint=self.c['source_fingerprint'],binary_sha256=self.c['binary']['sha256'],scope='native_app_input_fixture',
            os_input_verified=False,combat_death_verified=False,cases=entries)
    def verify(self):
        (self.folder/'run.json').write_text(json.dumps(self.run))
        # Invented source/manifest cannot provide actual admission; isolate the
        # output/process regression from that separately covered strict gate.
        with patch('verify_app_edges.check_source_status_identity'):
            return v.verify_run(self.folder,self.contract,self.pin,Path(__file__).resolve().parent)

class NativeReceiptTests(unittest.TestCase):
    def test_complete_invented_output_can_exercise_full_receipt_and_png_path(self):
        with tempfile.TemporaryDirectory() as d:
            f=NativeFixture(Path(d));r=f.verify();self.assertEqual(r['native_png_witnesses_verified'],12)
    def test_checkout_local_png_helpers_remain_byte_pinned(self):
        helpers=Path(__file__).resolve().parent
        for name,pin in v.HELPERS.items():
            with self.subTest(helper=name):self.assertEqual(v.sha(helpers/name),pin)
            with tempfile.TemporaryDirectory() as d:
                f=NativeFixture(Path(d))
                with patch.dict(v.HELPERS,{name:'f'*64}):
                    with self.assertRaisesRegex(v.Rejected,'PNG verifier helper changed'):f.verify()
    def reject(self,change,reason):
        with tempfile.TemporaryDirectory() as d:
            f=NativeFixture(Path(d));change(f)
            with self.assertRaisesRegex(v.Rejected,reason):f.verify()
    def test_original_boolean_false_exit_and_failed_guard_repros_reject(self):
        self.reject(lambda f:f.run['cases'][0].update(exit_code=False),'native process failed')
        self.reject(lambda f:f.run['cases'][0].update(resource_observation=dict(live_guard_active=False,guard_triggered=True,
            minimum_free_bytes=0,minimum_memory_available_bytes=0)),'native resource guard')
        for key,value in [('live_guard_active',False),('guard_triggered',True),('minimum_free_bytes',1073741824),('minimum_memory_available_bytes',1)]:
            with self.subTest(key=key):self.reject(lambda f:f.run['cases'][0]['resource_observation'].update({key:value}),'native resource guard')
    def test_original_unaccounted_output_and_directory_symlinks_reject(self):
        self.reject(lambda f:(f.folder/'pause/unreviewed-extra.txt').write_text('Invented extra output.\n'),'native output inventory')
        self.reject(lambda f:(f.folder/'unaccounted.log').write_text('Invented extra root output.\n'),'native output inventory')
        self.reject(lambda f:(f.folder/'pause/empty-unaccounted-directory').mkdir(),'native output inventory')
        self.reject(lambda f:(f.folder/'pause/linked').symlink_to(f.root/'source',target_is_directory=True),'native output symlink')
    def test_total_output_and_log_pins_are_bounded_before_decoding(self):
        with tempfile.TemporaryDirectory() as d:
            f=NativeFixture(Path(d));f.verify()
            with self.assertRaisesRegex(v.Rejected,'complete native output exceeds'):
                v.native_output_inventory(f.folder,dict(pause=6,reset=3,**{'debug-death':3}),'run.json',1)
        self.reject(lambda f:(f.folder/'pause/stdout.log').write_text('changed'),'native process log changed')
        self.reject(lambda f:f.run['cases'][0]['process_logs']['stdout'].update(bytes=2*1024**2+1),'native process log path/pin/bound')
    def test_failed_nonterminal_and_wrong_native_command_reject_in_complete_output(self):
        for field,value in [('exit_code',1),('completed',False),('timed_out',True),('process_group_terminal',False),('command',['wrong'])]:
            with self.subTest(field=field):self.reject(lambda f:f.run['cases'][0].update({field:value}),'native process failed')
if __name__=='__main__':unittest.main(verbosity=2)
