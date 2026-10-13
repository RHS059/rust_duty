"""Reconstruct exact retained ADS artifacts without extracting or executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'retention-manifest.json').read_text())
full, reports = manifest['artifacts']
expected = '893d34d04675678ca4f78de3ab970094b12787d7faa363fc291f75b31b901a0b'
report_hash = 'd749f5220070d0c02f67f7c3f2c801ccba33a32322f5829e51ecd58830174599'
if full['sha256'] != expected or reports['sha256'] != report_hash or len(full['parts']) != 7:
    raise ValueError('Unexpected original archive manifest')
digest = hashlib.sha256()
total = 0
with args.output.open('xb') as output:
    for index, part in enumerate(full['parts']):
        if part['index'] != index or part['offset'] != total or part['name'] != f'resident-ads-all.zip.part{index:03d}':
            raise ValueError('Invalid part order or filename')
        data = (root / part['name']).read_bytes()
        if len(data) != part['bytes'] or hashlib.sha256(data).hexdigest() != part['sha256']:
            raise ValueError('Part integrity mismatch')
        output.write(data)
        digest.update(data)
        total += len(data)
if total != 42432817 or digest.hexdigest() != expected:
    raise ValueError('Original full ZIP mismatch')
report_path = root / 'resident-ads-reports-attempt-1.zip'
if report_path.stat().st_size != 297639 or hashlib.sha256(report_path.read_bytes()).hexdigest() != report_hash:
    raise ValueError('Original report ZIP mismatch')
for path, count in [(args.output, 4714), (report_path, 26)]:
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) != count or archive.testzip() is not None:
            raise ValueError('ZIP entry count or CRC mismatch')
print(json.dumps({'verified': True, 'full_sha256': expected, 'reports_sha256': report_hash}))
