"""Exact v1 renderer diagnostic composition; never admits native evidence.

The historical consolidated source contract remains immutable. These byte pins
and the two pinned insertions establish a successor, not a replacement history.
"""
import hashlib
import json
from pathlib import Path

CONTRACT_SHA256 = "dc4fd33f708d0885db40d76a10118b2b748f0315d4f39d66905b980e164eae42"
HISTORICAL_CONTRACT_SHA256 = "772ac58692cfb00578bd2af552fcbc7e312c78f6000a6caa5b18911981b338ee"


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def load_overlay():
    raw = Path(__file__).with_suffix('.json').read_bytes()
    require(sha256(raw) == CONTRACT_SHA256, 'diagnostic overlay contract bytes changed')
    return json.loads(raw)


def historical_contract(raw):
    require(sha256(raw) == HISTORICAL_CONTRACT_SHA256,
            'historical consolidated source contract bytes changed')
    return json.loads(raw)


def apply_renderer_overlay(parent, provenance):
    contract = load_overlay()
    history = historical_contract(provenance)
    require(sha256(parent) == contract['parent_sha256'] == history['repository_renderer_sha256'],
            'diagnostic overlay parent renderer bytes changed')
    text = parent.decode('utf-8')
    for row in contract['insertions']:
        require(text.count(row['before']) == 1, 'diagnostic overlay insertion anchor changed')
        require(row['insert'] not in text, 'diagnostic overlay already present')
        text = text.replace(row['before'], row['insert'] + row['before'])
    current = text.encode('utf-8')
    require(sha256(current) == contract['current_sha256'], 'composed renderer bytes changed')
    return current


def restore_renderer_overlay(current, provenance):
    contract = load_overlay()
    history = historical_contract(provenance)
    require(sha256(current) == contract['current_sha256'],
            'diagnostic overlay current renderer bytes changed')
    text = current.decode('utf-8')
    for row in reversed(contract['insertions']):
        combined = row['insert'] + row['before']
        require(text.count(row['insert']) == 1 and text.count(combined) == 1,
                'diagnostic overlay insertion is changed, missing, duplicated, or moved')
        text = text.replace(combined, row['before'])
    parent = text.encode('utf-8')
    require(sha256(parent) == contract['parent_sha256'] == history['repository_renderer_sha256'],
            'restored historical renderer bytes changed')
    require(apply_renderer_overlay(parent, provenance) == current,
            'diagnostic overlay round trip changed source')
    return parent
