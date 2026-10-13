"""Reconstruct and verify retained evidence; never execute or extract its contents."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True,
                    help='New directory for the reconstructed XZ and original ZIP')
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
expected_xz = 'fb2055d959c44f576cd9e14a9a453e020f745ad38cac66fd0af92f45e68b7dea'
expected_zip = '7a75575364990e4963f012e2ee8dad5a75a14595a351f3c4d618033cdbbc6237'
if manifest['compressed']['sha256'] != expected_xz or manifest['original']['sha256'] != expected_zip:
    raise ValueError('Manifest does not describe the published original evidence')
args.output_dir.mkdir(parents=True, exist_ok=False)
xz_path = args.output_dir / 'a100-0476992-full-exact-color-r1-stored.zip.xz'
zip_path = args.output_dir / 'a100-0476992-full-exact-color-r1-stored.zip'
whole = hashlib.sha256()
total = 0
if len(manifest['parts']) != 4:
    raise ValueError('Expected exactly four parts')
with xz_path.open('xb') as output:
    for index, part in enumerate(manifest['parts']):
        if part['index'] != index or part['offset'] != total or part['name'] != f'a100-exact-color.xz.part{index:03d}':
            raise ValueError('Part order, offset or filename is invalid')
        data = (root / part['name']).read_bytes()
        if len(data) != part['bytes'] or hashlib.sha256(data).hexdigest() != part['sha256']:
            raise ValueError(f'Part {index} does not match its manifest')
        output.write(data)
        whole.update(data)
        total += len(data)
if total != 21177536 or whole.hexdigest() != expected_xz:
    raise ValueError('Combined XZ hash or size mismatch')
whole = hashlib.sha256()
total = 0
with lzma.open(xz_path, 'rb') as source, zip_path.open('xb') as output:
    while True:
        block = source.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > 625606155:
            raise ValueError('Decompressed archive exceeds expected size')
        whole.update(block)
        output.write(block)
if total != 625606155 or whole.hexdigest() != expected_zip:
    raise ValueError('Original ZIP hash or size mismatch')
with zipfile.ZipFile(zip_path) as archive:
    if len(archive.infolist()) != 603 or archive.testzip() is not None:
        raise ValueError('Original ZIP entry count or CRC mismatch')
print(json.dumps({'verified': True, 'zip': str(zip_path), 'bytes': total,
                  'sha256': expected_zip, 'entries': 603, 'crc': 'PASS'}, indent=2))
