"""Small local index/checkout fixture; no commits, remotes, network or publication."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


def checkout_fixture():
    git=shutil.which('git')
    if not git:raise AssertionError('Git is required for the pinned-byte checkout fixture')
    with tempfile.TemporaryDirectory(prefix='runtime-v2-checkout-') as folder:
        root=Path(folder);repo=root/'repo';repo.mkdir();target=root/'checkout';target.mkdir()
        env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
        def run(*args):
            return subprocess.run([git,*args],cwd=repo,env=env,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        run('init','--quiet')
        package=repo/'package';package.mkdir()
        attributes=(HERE/'.gitattributes').read_bytes();(package/'.gitattributes').write_bytes(attributes)
        fixtures={f.name:f.read_bytes() for f in HERE.iterdir() if f.is_file()}
        fixtures.update({'lf.txt':b'first\nsecond\n','mixed.dat':b'first\r\nsecond\n\x00last\r\n'})
        assert sum(map(len,fixtures.values()))<10*1024**2
        for name,data in fixtures.items():(package/name).write_bytes(data)
        run('-c','core.autocrlf=true','add','--','package')
        check=run('check-attr','--cached','text','--',*['package/'+name for name in fixtures]).decode()
        assert check.count('text: unset')==len(fixtures),check
        # Leave the attributes only in the index. Checkout must still use them.
        (package/'.gitattributes').unlink()
        run('-c','core.autocrlf=true','-c','core.eol=crlf','checkout-index',
            '--prefix='+str(target)+os.sep,'--',*['package/'+name for name in fixtures])
        records={}
        for name,original in fixtures.items():
            indexed=run('show',':package/'+name);checked=(target/'package'/name).read_bytes()
            assert original==indexed==checked,name
            records[name]={'bytes':len(original),'source_sha256':hashlib.sha256(original).hexdigest(),
                'index_sha256':hashlib.sha256(indexed).hexdigest(),'checkout_sha256':hashlib.sha256(checked).hexdigest()}
        return {'schema':'rust-duty-runtime-consumer-checkout-fixture/v1','git':run('--version').decode().strip(),
            'core_autocrlf':True,'core_eol':'crlf','working_tree_attributes_absent':True,
            'cached_attribute_check':check.splitlines(),'attributes_sha256':hashlib.sha256(attributes).hexdigest(),
            'fixtures':records,'exact_bytes_preserved':True,'actual_windows_checkout':os.name=='nt',
            'commits_or_remote_operations':False}

class CheckoutByteTests(unittest.TestCase):
    def test_package_attributes_preserve_indexed_and_checkout_bytes(self):
        self.assertTrue(checkout_fixture()['exact_bytes_preserved'])

if __name__=='__main__':unittest.main(verbosity=2)
