"""Immutable original source bytes for source-admission unit tests only."""
import hashlib
from pathlib import Path
import zipfile

import performance_matrix as matrix

FIXTURES = Path(__file__).resolve().parent / 'test_fixtures'


def _read_archive(name, archive_sha256, manifest_sha256, count, paths=None):
    path = FIXTURES / name
    matrix.require(matrix.sha256(path) == archive_sha256, 'Historical test archive changed')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        matrix.require(len(names) == len(set(names)) == count, 'Historical test inventory changed')
        if paths is not None:
            matrix.require(set(names) == set(paths), 'Historical test source paths changed')
        files = {name: archive.read(name) for name in names}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    matrix.require(matrix.canonical_hash(hashes) == manifest_sha256,
                   'Historical test source digest changed')
    return files


def skin_stage_sources():
    return _read_archive('skin-stage-source-663d191.zip',
                        'f534904b8dae31637d6983576679e3d16f477a5ff0026da921e18ad1299e2c4d',
                        'b531276d331ff2addea10aec89eea7eb743cbab89858709194cdc8286fc32a96',
                        48, matrix.ARITHMETIC_SOURCE_PATHS)


def resident_ads_sources():
    return _read_archive('resident-ads-source-2a1776a.zip',
                        '1cde55bca938ebe6c6afc942b88824e93d12620ec7814e467250cbb6aa95c8b6',
                        '2a6a534aec6e3a6053ed6584dac497e38f85fabcf47aecf64c209bc925460b17',
                        131)
