"""Read-only verification of frozen process evidence. Never launches a process."""
import hashlib
from pathlib import Path
import sys
from types import ModuleType
import uuid
from candidate_context import file_sha, ordinary, require

TRANSPORT_SHA = 'fc9487442489c0e444f03afb549c815e444aec4b76d0e1ed4d4f3160f7d63baa'
TRANSPORT_PINS_SHA = 'a5c9ad4ab20f45c5f1d90e3011ef74d07388f2daca11e2faf8966794fe2f0d00'


def load_integrity_reader(package):
    package = ordinary(package, existing=True)
    require(file_sha(package / 'PINS.json') == TRANSPORT_PINS_SHA, 'transport manifest changed')
    path = package / 'owned_process.py'
    require(file_sha(path) == TRANSPORT_SHA, 'transport verifier changed')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == TRANSPORT_SHA, 'transport changed while reading')
    name = '_onehand_readonly_transport_' + uuid.uuid4().hex
    module = ModuleType(name); module.__file__ = str(path)
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    finally:
        del sys.modules[name]
    return module.verify_attempt


def require_production_transport():
    # This revision is intentionally blocked, regardless of OS or file presence.
    # A new reviewed source revision must update pins and tests for transport v2.
    require(False, 'transport v1 blocked: false EOF completion, writer-handle cleanup failure, '
                   'and pending OVERLAPPED cancellation/drain failure; reviewed version required')


def load_verifier(package):
    """Production gate: v1 must never authorize assembly after the review denial."""
    require_production_transport()
    return load_integrity_reader(package)
