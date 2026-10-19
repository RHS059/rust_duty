import copy,gzip,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import parts_transport as p
import source_transport as t
HERE=Path(__file__).absolute().parent

def identity(raw):return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

class Parts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.raw=bytes(range(256))*1025;self.encoded=gzip.compress(self.raw,mtime=0)
        self.expected={'name':'synthetic.json','canonical':identity(self.raw),'reconstructed':identity(self.encoded),'parts':[]};self.blobs={}
        for i in range(0,len(self.encoded),p.PART_SIZE):
            raw=self.encoded[i:i+p.PART_SIZE];name=f'parts/synthetic.json/{i//p.PART_SIZE:03d}.gzpart';self.blobs[p.PREFIX+name]=raw
            self.expected['parts'].append({'path':name,**identity(raw),'blob_sha1':blob(raw)})
        self.parts=[{'ref':'a'*40,'repository_path':p.PREFIX+r['path'],**{k:r[k] for k in ('sha256','bytes','blob_sha1')}} for r in self.expected['parts']]
    def tearDown(self):self.tmp.cleanup()
    def read(self,ref,path,size):return self.blobs[path]
    def test_same_gzip_then_exact_decoded_bytes(self):
        target=self.root/'fresh.gz';self.assertEqual(p.reconstruct(self.parts,self.expected,target,self.read),identity(self.encoded))
        writes=[];t.decode_verified(target,identity(self.encoded),identity(self.raw),writes.append)
        self.assertEqual(b''.join(writes),self.raw)
    def test_three_large_parts_are_ordered_and_bounded(self):
        import random
        encoded=gzip.compress(random.Random(812).randbytes(150000),mtime=0)
        expected={'name':'three.json','reconstructed':identity(encoded),'parts':[]};blobs={}
        for i in range(0,len(encoded),p.PART_SIZE):
            raw=encoded[i:i+p.PART_SIZE];name=f'parts/three.json/{i//p.PART_SIZE:03d}.gzpart';blobs[p.PREFIX+name]=raw
            expected['parts'].append({'path':name,**identity(raw),'blob_sha1':blob(raw)})
        parts=[{'ref':'b'*40,'repository_path':p.PREFIX+r['path'],**{k:r[k] for k in ('sha256','bytes','blob_sha1')}} for r in expected['parts']]
        self.assertEqual(len(parts),3)
        target=self.root/'three.gz';p.reconstruct(parts,expected,target,lambda ref,path,size:blobs[path]);self.assertEqual(target.read_bytes(),encoded)
        with self.assertRaises(ValueError):p.validate_git_parts(list(reversed(parts)),expected)

    def test_missing_reordered_wrong_parts_rejected(self):
        for parts in ([],self.parts+self.parts,[{**self.parts[0],'sha256':'0'*64}], [{**self.parts[0],'ref':None}]):
            with self.assertRaises(ValueError):p.validate_git_parts(parts,self.expected)
    def test_part_bytes_fail_before_output_data(self):
        with self.assertRaises(ValueError):p.reconstruct(self.parts,self.expected,self.root/'bad.gz',lambda *_:b'wrong')
        self.assertEqual((self.root/'bad.gz').stat().st_size,0)
    def test_reconstructed_identity_must_match(self):
        wrong=copy.deepcopy(self.expected);wrong['reconstructed']['sha256']='0'*64
        with self.assertRaises(ValueError):p.reconstruct(self.parts,wrong,self.root/'bad.gz',self.read)
    def test_disk_reservation_is_fail_closed(self):
        with patch.object(p.shutil,'disk_usage',return_value=type('D',(),{'free':p.DISK_FLOOR})()),self.assertRaises(ValueError):p.reconstruct(self.parts,self.expected,self.root/'out.gz',self.read)
        self.assertFalse((self.root/'out.gz').exists())
    def test_fixed_catalog_is_complete_and_bounded(self):
        catalog=json.loads((HERE/'TRANSPORT_PARTS.json').read_bytes());rows=t.validate_manifest(json.loads((HERE/'TRANSPORT_MANIFEST.json').read_bytes()))
        checked=p.validate_catalog(catalog,rows,hashlib.sha256((HERE/'TRANSPORT_MANIFEST.json').read_bytes()).hexdigest())
        self.assertEqual(len(checked),38);self.assertEqual(sum(len(r['parts']) for r in checked),123)
        self.assertLessEqual(max(part['bytes'] for r in checked for part in r['parts']),65536)
    def test_catalog_missing_or_out_of_order_rejected(self):
        catalog=json.loads((HERE/'TRANSPORT_PARTS.json').read_bytes());rows=t.validate_manifest(json.loads((HERE/'TRANSPORT_MANIFEST.json').read_bytes()));sha=hashlib.sha256((HERE/'TRANSPORT_MANIFEST.json').read_bytes()).hexdigest()
        for change in ('missing','reorder','oversize','badpath','canonical'):
            c=copy.deepcopy(catalog)
            if change=='missing':c['files'].pop()
            elif change=='reorder':c['files'][0]['parts'].reverse()
            elif change=='oversize':c['files'][0]['parts'][0]['bytes']=65537
            elif change=='badpath':c['files'][0]['parts'][0]['path']='../x'
            else:c['files'][0]['canonical']['sha256']='0'*64
            with self.subTest(change=change),self.assertRaises(ValueError):p.validate_catalog(c,rows,sha)

if __name__=='__main__':unittest.main()
