"""Synthetic completed-input tests. No native execution or real decoded copies."""
import copy,gzip,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import checkout_bytes as c

def ident(raw):return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

class CompletedInputs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.raw=b'{"synthetic":"bounded"}\n'*100;self.encoded=gzip.compress(self.raw,mtime=0)
        part={'path':'parts/synthetic.json/000.gzpart',**ident(self.encoded),'blob_sha1':blob(self.encoded)}
        self.expected={'name':'synthetic.json','canonical':{'path':'hash-only-reference/synthetic.json',**ident(self.raw)},'kind':'hash-only-reference','reconstructed':{'path':'payload/synthetic.json.gz',**ident(self.encoded)},'parts':[part]}
        self.row={'destination':self.expected['canonical']['path'],'kind':'hash-only-reference','canonical':ident(self.raw),'encoding':'gzip-single-member','transport':{'manifest_repository_path':c.TRANSPORT_PREFIX+'TRANSPORT_PARTS.json',**ident(self.encoded)},'git':{'parts':[{'ref':'a'*40,'repository_path':c.TRANSPORT_PREFIX+part['path'],**ident(self.encoded),'blob_sha1':blob(self.encoded)}]}}
    def tearDown(self):self.tmp.cleanup()
    def manifest(self):return {'schema':c.V2_SCHEMA,'files':[copy.deepcopy(self.row)]}
    def validate(self,m):
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]):return c.validate_manifest(m)
    def test_fixed_complete_real_manifest_requires_38_gzip_inputs(self):
        self.assertEqual(len(c.canonical_transport_rows()),38)
        with self.assertRaises(ValueError):c.validate_manifest(self.manifest())
    def test_small_success_has_distinct_git_and_canonical_receipt(self):
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]):
            receipt=c.materialize(self.manifest(),self.root/'out',lambda *_:self.encoded)
        row=receipt['files'][0];self.assertEqual((self.root/'out'/row['destination']).read_bytes(),self.raw)
        self.assertEqual(row['canonical'],ident(self.raw));self.assertEqual(row['transport']['sha256'],ident(self.encoded)['sha256'])
        self.assertNotEqual(row['canonical']['sha256'],row['transport']['sha256']);self.assertFalse(receipt['byte_preserving_git_blobs']);self.assertFalse(receipt['native_admission'])
    def test_mixed_identity_and_encoded_sources(self):
        m=self.manifest();raw=b'pub fn source() {}\n';g={'ref':'b'*40,'repository_path':'src/x.rs',**ident(raw),'blob_sha1':blob(raw)}
        m['files'].append({'destination':'rust-source/src/x.rs','kind':'original-source','canonical':ident(raw),'encoding':'identity','git':g})
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]):
            receipt=c.materialize(m,self.root/'out',lambda ref,*_:raw if ref=='b'*40 else self.encoded)
        self.assertEqual(receipt['files'][1]['sha256'],g['sha256'])
    def test_canonical_gzip_or_git_hash_mismatch(self):
        for domain,key,value in [('canonical','sha256','0'*64),('canonical','bytes',1),('transport','sha256','0'*64),('transport','bytes',1)]:
            m=self.manifest();m['files'][0][domain][key]=value
            with self.assertRaises(ValueError):self.validate(m)
    def test_encoded_blob_hash_checked_before_decode(self):
        m=self.manifest();m['files'][0]['git']['parts'][0]['blob_sha1']='0'*40
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]),self.assertRaisesRegex(ValueError,'part identity'):
            c.materialize(m,self.root/'out',lambda *_:self.encoded)
        self.assertFalse((self.root/'out'/self.row['destination']).exists())
    def test_swapped_missing_duplicate_extra_and_wrong_encoding(self):
        for change in ('missing','duplicate','extra','encoding','renamed'):
            m=self.manifest()
            if change=='missing':m['files']=[]
            elif change=='duplicate':m['files']*=2
            elif change=='extra':m['files'][0]['hidden']=True
            elif change=='encoding':m['files'][0]['encoding']='identity'
            else:m['files'][0]['destination']='hash-only-reference/other.json'
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate(m)
    def test_bad_git_bytes_fail_before_decode(self):
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]),self.assertRaisesRegex(ValueError,'part bytes'):
            c.materialize(self.manifest(),self.root/'out',lambda *_:self.encoded+b'x')
    def test_full_reservation_failure_creates_no_root(self):
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]),patch.object(c.shutil,'disk_usage',return_value=type('D',(),{'free':c.DISK_FLOOR})()),self.assertRaises(ValueError):
            c.materialize(self.manifest(),self.root/'out',lambda *_:self.encoded)
        self.assertFalse((self.root/'out').exists())
    def test_existing_destination_refused(self):
        with patch.object(c,'canonical_transport_rows',return_value=[self.expected]),self.assertRaises(ValueError):
            c.materialize(self.manifest(),self.root,lambda *_:self.encoded)
    def test_encoded_staging_namespace_reserved(self):
        m=self.manifest();m['files'][0]['destination']='.encoded-transport/x'
        with self.assertRaises(ValueError):self.validate(m)
    def test_nonfinite_duplicate_json_fail(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            with self.assertRaises(ValueError):c.strict_load(raw)

if __name__=='__main__':unittest.main()

class SourceSelection(unittest.TestCase):
    def test_exact_c61_closure(self):
        import source_selection as s
        selected=s.selection();files={r['path']:r['sha256'] for r in selected['files']}
        s.verify(files,s.REVISION,[])
        for mutate in ('extra','missing','changed'):
            other=dict(files)
            if mutate=='extra':other['foreign.rs']='a'*64
            elif mutate=='missing':other.pop('src/lib.rs')
            else:other['src/lib.rs']='a'*64
            with self.assertRaises(ValueError):s.verify(other,s.REVISION,[])
    def test_actual_compiler_cannot_be_linux_or_moving_stable(self):
        import source_selection as s
        s.verify_compiler('rustc 1.99.0\nrelease: 1.99.0\nhost: x86_64-pc-windows-msvc\n')
        for text in ('rustc 1.99.0\nrelease: 1.99.0\nhost: x86_64-unknown-linux-gnu\n','rustc 1.99.0\nrelease: 1.99.1\nhost: x86_64-pc-windows-msvc\n'):
            with self.assertRaises(ValueError):s.verify_compiler(text)
