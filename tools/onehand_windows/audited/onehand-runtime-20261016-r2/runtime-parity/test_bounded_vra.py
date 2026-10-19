"""Complete decoder equivalence/corruption tests, without native execution."""
import copy
import json
from pathlib import Path
import resource
import struct
import tempfile
import unittest
import zlib
import onehand_r2_common as c
import bounded_vra as b

D=c.G.vrview


def fixture(frame_count=2):
    payload=bytearray();offsets={}
    def add(tag,fmt,*values):
        offsets[tag]=len(payload);payload.extend(struct.pack(fmt,*values))
    def name(tag,value):
        raw=value.encode();add(tag+'_length','<H',len(raw));offsets[tag]=len(payload);payload.extend(raw)
    add('skin_crc','<I',0);add('mesh_crc','<I',0);add('bone_count','<I',2)
    for i in range(2):name('bone'+str(i),'b'+str(i));add('parent'+str(i),'<i',i-1)
    add('actor_count','<I',2)
    identity=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
    for i in range(2):
        name('actor'+str(i),'a'+str(i));add('mesh_count'+str(i),'<I',1);add('mesh'+str(i),'<I',i)
        add('inverse'+str(i),'<16f',*identity)
    add('clip_count','<I',2)
    for clip in range(2):
        name('clip'+str(clip),'c'+str(clip));add('flags'+str(clip),'<I',0);add('frame_count'+str(clip),'<I',frame_count)
        for frame in range(frame_count):
            add(f'time{clip}_{frame}','<f',frame/60)
            for transform in range(4):add(f'trs{clip}_{frame}_{transform}','<10f',0.,0.,0.,0.,0.,0.,1.,1.,1.,1.)
            add(f'visibility{clip}_{frame}','<2B',1,0)
    return wrap(payload),offsets


def wrap(payload):
    return D.HEADER.pack(D.MAGIC,D.VERSION,len(payload),zlib.crc32(payload),0)+payload


def mutate(data,offset,fmt,*values):
    payload=bytearray(data[D.HEADER.size:]);struct.pack_into(fmt,payload,offset,*values)
    return wrap(payload)


class BoundedVraTests(unittest.TestCase):
    def both_reject(self,data,**kwargs):
        for decoder in (D.decode_vra,b.scan_buffer):
            with self.assertRaises((ValueError,struct.error,IndexError,UnicodeError)):
                decoder(data,**kwargs)
    def test_small_fixture_matches_exact_decoder_metadata(self):
        data,_=fixture()
        self.assertEqual(b.scan_buffer(data),b.metadata_only(D.decode_vra(data)))
        self.assertTrue(all(set(frame)=={'time'} for clip in b.scan_buffer(data)['clips'] for frame in clip['frames']))
    def test_read_only_mmap_matches_small_reference(self):
        data,_=fixture()
        with tempfile.TemporaryDirectory(dir=c.HERE) as directory:
            path=Path(directory)/'synthetic.vra';path.write_bytes(data)
            self.assertEqual(b.scan_vra(path),b.metadata_only(D.decode_vra(data)))
            self.assertEqual(path.read_bytes(),data)
    def test_header_crc_truncation_and_trailing_bytes(self):
        data,_=fixture()
        for offset,fmt,value in [(0,'<8s',b'BADMAGIC'),(8,'<I',2),(12,'<I',1),(16,'<I',0),(20,'<I',1)]:
            bad=bytearray(data);struct.pack_into(fmt,bad,offset,value);self.both_reject(bad)
        for bad in (b'',data[:20],data[:-1],wrap(data[D.HEADER.size:]+b'x')):self.both_reject(bad)
    def test_every_inventory_parent_name_and_mesh_rule(self):
        data,o=fixture()
        changes=[('bone_count','<I',0),('bone_count','<I',129),('bone0_length','<H',0),('bone0_length','<H',129),
                 ('bone0','<2s',b'\xffx'),('bone0','<2s',b'\0x'),('parent1','<i',1),('parent0','<i',-2),
                 ('actor_count','<I',257),('actor1','<2s',b'a0'),('mesh_count0','<I',257),('mesh0','<I',256),
                 ('mesh1','<I',0),('inverse0','<f',float('nan')),('clip_count','<I',0),('clip_count','<I',129),
                 ('clip1','<2s',b'c0'),('flags0','<I',2),('frame_count0','<I',0),('frame_count0','<I',65537)]
        for tag,fmt,value in changes:
            with self.subTest(tag=tag,value=value):self.both_reject(mutate(data,o[tag],fmt,value))
    def test_all_time_and_trs_validity_rules(self):
        data,o=fixture()
        for tag,value in [('time0_0',1.),('time0_1',0.),('time0_1',float('nan')),('time0_1',float('inf'))]:
            self.both_reject(mutate(data,o[tag],'<f',value))
        for component,value in [(0,float('nan')),(0,10001.),(0,-10001.),(6,1.01),(7,0.),(7,1e-9),(8,-1.),(9,10001.)]:
            self.both_reject(mutate(data,o['trs0_0_0']+4*component,'<f',value))
        self.both_reject(mutate(data,o['visibility0_0'],'<B',2))
    def test_corruption_at_last_frame_last_transform_not_skipped(self):
        data,o=fixture(frame_count=150)
        self.both_reject(mutate(data,o['trs1_149_3']+36,'<f',0.))
    def test_transform_budget_and_remaining_payload_checked(self):
        data,o=fixture()
        # 65,536 frames passes the frame cap but payload is absent.
        self.both_reject(mutate(data,o['frame_count0'],'<I',65536))
        # A valid tiny container with >2M declared transforms rejects before data.
        payload=bytearray(struct.pack('<III',0,0,128))
        for i in range(128):
            name=f'b{i}'.encode();payload+=struct.pack('<H',len(name))+name+struct.pack('<i',i-1)
        payload+=struct.pack('<II',0,1)+struct.pack('<H',1)+b'c'+struct.pack('<II',0,65536)
        self.both_reject(wrap(payload))
    def test_companion_validation_not_skipped(self):
        data,_=fixture()
        for kwargs in ({'vrs':b'invalid'},{'vrm':b'invalid'}):self.both_reject(data,**kwargs)
    def test_old_real_vra_summary_equivalence_if_memory_allows(self):
        mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line and len(line.split())>=2 and line.split()[1].isdigit()}
        if mem.get('MemAvailable',0)<1024**3:self.skipTest('one GiB available-memory budget required for old decoder comparison')
        root=c.ORIGINAL_WORK/'runtime-v1'
        data=(root/'asset.vra').read_bytes();vrs=(root/'asset.vrs').read_bytes();vrm=(root/'asset.vrm').read_bytes()
        c.pin(root/'asset.vra','92dc118b360b54585b799968c7db241f4e711d8d6b40b7ce2f05f8910a88e5b4')
        reference=D.decode_vra(data,vrs=vrs,vrm=vrm)
        self.assertEqual(b.scan_vra(root/'asset.vra',vrs=vrs,vrm=vrm),b.metadata_only(reference))
        self.assertEqual(len(reference['clips'][0]['frames']),6081)
        self.assertEqual(c.sha(root/'asset.vra'),'92dc118b360b54585b799968c7db241f4e711d8d6b40b7ce2f05f8910a88e5b4')

if __name__=='__main__':unittest.main()
