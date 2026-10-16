"""Strict bounded one-hand v6 parity identities and audited generic helpers.

The prone verifier is imported read-only solely for geometry/container primitives.
Its prone timing, camera, source validators and checker are never invoked.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent
ORIGINAL_WORK = ROOT / "onehand-runtime-20261016"
SUBDIVISIONS = 256
RUNTIME_HZ = 60 * SUBDIVISIONS
RUNTIME_KEYS = 95 * SUBDIVISIONS + 1
FRAME1_SHA = "935e14ca347a273851e2f275661fef41aaf905905b437934aec724ed79d27f7d"
SOURCE_SHA = 'b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
ACTION = 'aella_mantle_onehand_r6_camera_reconstructed_v6'
ACTION_SHA = 'c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01'
GRID_SHA = 'a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f'
CANONICAL_SHA = 'd02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab'
SAMPLER_SHA = '8f8de71a2fca6f36469dd520d3b1a14c43f0839f91c910faa4974e3a91916fcb'
ACTORS = ('hk416_weapon', 'hk416_magazine', 'hk416_magazine_outgoing')
COUNTS = (5710, 3954, 570)
SKINS = tuple(f'Actual arms mesh {i}' for i in range(3))
LIMIT = 1e-4
RAY_LIMIT = 1e-5
TOTAL_SAMPLES = 4240
TOTAL_OBSERVATIONS = 43392160
CHUNK_COUNT = 67
CHUNK_SIZE = 64
THRESHOLDS = {'position_m': LIMIT, 'matrix_element': LIMIT, 'source_fbx_projection_ray': RAY_LIMIT}
BASIS = np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]], dtype=float)
HELPERS = {
 'verify_prone_r15_runtime.py': 'b8bbc01d16e703934626ceff88f328a19345ded859a01f36f0918dbadd470d8b',
 'vrview.py': 'eefd755f6ef0943a4d8bf443ddfec601bc1336ec90ece722d017c9c4b6d73568',
 'vrskin.py': 'e6aff7f5278bb8e6dd09ca75e69b8761b1b71bd30b3feddf84f8380cd88a5e14',
 'vrpack.py': '28a23ed9a9b0fe0123405a9800473e57d04419596deae8789c66c744ad05b685',
 'prone_camera_pair.py': 'd454764dcbacfa0fc541111c45fc7ed572fbbb19c95eca3552a0db982a8ef1b8',
 'prone_r15_equivalence_contract.json': '313f980a3fcf4d24676c5b48a79fb5c2b032cd3cbef225c24c0c13c986e5e93b',
}

class AdmissionError(ValueError):
    pass

def require(value, message):
    if not value:
        raise AdmissionError(message)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def pin(path, expected):
    require(sha(path) == expected, 'hash differs: ' + str(path))
    return expected

def unique(pairs):
    value = {}
    for key, entry in pairs:
        require(key not in value, 'duplicate JSON key: ' + key)
        value[key] = entry
    return value

def loads(text):
    def invalid(value):
        raise AdmissionError('non-finite JSON number: ' + value)
    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)

def read(path):
    return loads(Path(path).read_text())

def write_new(path, data):
    path = Path(path)
    require(path.resolve().is_relative_to(HERE), 'output outside runtime-parity')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(data, indent=2, allow_nan=False) + '\n')

def bounded(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
            and '..' not in Path(relative).parts, 'unsafe evidence path')
    path = Path(root)/relative
    require(not path.is_symlink() and path.resolve().is_relative_to(Path(root).resolve()), 'evidence path escapes root')
    return path

def finite_number(value, label):
    require(type(value) in (int,float) and math.isfinite(value), 'invalid numeric ' + label)
    return value

def exact(value, expected, label):
    require(type(value) is type(expected) and value == expected, 'mismatch: ' + label)

def grid():
    path = ROOT/'recovery/onehand-v6-integration-handoff/dense-times.json'
    pin(path, GRID_SHA)
    values = read(path)
    require(len(values)==TOTAL_SAMPLES and values==sorted(set(values)) and values[0]==1 and values[-1]==96, 'invalid exact source grid')
    require(all(type(v) is float and math.isfinite(v) for v in values), 'exact exported grid requires float JSON values')
    return values

def frames(index):
    require(type(index) is int and 0 <= index < CHUNK_COUNT, 'invalid chunk index')
    return grid()[index*CHUNK_SIZE:(index+1)*CHUNK_SIZE]

def helper():
    directory = ROOT/'prone-r15-runtime-20261016/source/tools'
    for name, expected in HELPERS.items():
        pin(directory/name, expected)
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('_onehand_audited_geometry', directory/'verify_prone_r15_runtime.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

G = helper()

class FrozenMap:
    """Serialized bidirectional frame-1 maps, never rematched after initialization."""
    def __init__(self, value):
        require(value.get('kind') == 'frame1-bidirectional' and value.get('frame') == 1, 'invalid mapping origin')
        self.actual_count = value['actual_count']
        self.expected_count = value['expected_count']
        require(type(self.actual_count) is int and self.actual_count>0 and type(self.expected_count) is int and self.expected_count>0, 'invalid mapping dimensions')
        for field, size, maximum in [('forward',self.actual_count,self.expected_count),('reverse',self.expected_count,self.actual_count)]:
            entries = value.get(field)
            require(isinstance(entries,list) and len(entries)==size and all(type(v) is int and 0<=v<maximum for v in entries), 'invalid mapping indices')
        self.forward = np.array(value['forward'], dtype=np.int64)
        self.reverse = np.array(value['reverse'], dtype=np.int64)
        self.value = value
        require(0 <= finite_number(value['initial_error_m'],'mapping error') < LIMIT, 'mapping threshold exceeded')
    @classmethod
    def establish(cls, actual, expected):
        mapped = G.FixedCorrespondence(actual, expected)
        return cls({'kind':'frame1-bidirectional','frame':1,'actual_count':len(actual),'expected_count':len(expected),
                    'forward':mapped.forward.tolist(),'reverse':mapped.reverse.tolist(),'initial_error_m':mapped.initial_error})
    def error(self, actual, expected):
        actual = G.finite(actual, (self.actual_count,3), 'mapped runtime geometry')
        expected = G.finite(expected, (self.expected_count,3), 'mapped source geometry')
        return max(float(np.linalg.norm(actual-expected[self.forward], axis=1).max()),
                   float(np.linalg.norm(actual[self.reverse]-expected, axis=1).max()))

SPEC_SCHEMA='rust-duty-onehand-candidate-spec/v2'
CANDIDATE_SCHEMA='rust-duty-onehand-accepted-candidate/v2'
FOCUS_FRAMES=[55.65625+i/512 for i in range(9)]
ASSET_PATHS={'fbx':'dense-output-v1/aella_onehand_camera_reconstructed_v6.fbx',
             'asset.vra':'runtime-v1/asset.vra','asset.vrs':'runtime-v1/asset.vrs',
             'asset.vrm':'runtime-v1/asset.vrm','manifest':'runtime-v1/manifest.json'}


def check_proof_root():
    require(WORK.name=='onehand-runtime-20261016-r2' and WORK.parent==ROOT,'fresh sibling proof root differs')
    require(WORK.resolve()!=ORIGINAL_WORK.resolve() and not WORK.is_symlink(),'old or symlinked proof root forbidden')


def safe_output(relative):
    check_proof_root()
    result=bounded(WORK,relative)
    require(result.resolve().is_relative_to(WORK.resolve()) and not result.resolve().is_relative_to(ORIGINAL_WORK.resolve()),'output may not enter old proof')
    current=result
    while current!=WORK:
        require(not current.is_symlink(),'output symlink component forbidden')
        current=current.parent
    return result


def validate_spec(spec):
    for key,value in {'schema':SPEC_SCHEMA,'source_sha256':SOURCE_SHA,'action':ACTION,'action_fingerprint':ACTION_SHA,
                      'sample_grid_sha256':GRID_SHA,'fbx_subdivisions':256,'runtime_subdivisions':256,
                      'runtime_hz':15360,'runtime_keys':24321,'native_crop':[0,95],'native_fps':[60,1],
                      'samples':4240,'chunks':67,'chunk_size':64,'source_skin_observations':43392160,
                      'thresholds':THRESHOLDS,'static_camera':True,'static_rig':True,'switches':[],
                      'float32_collision_policy':'reject','rigid_frame1_sha256':FRAME1_SHA,
                      'old_coverage_carryover':False,'asset_hashes':{},'acceptance_required':True,
                      'asset_pins_at_preparation':'pending','representation_focus_frames':FOCUS_FRAMES,
                      'focus_output':'focus-output-v2','window_control_output':'window-control-v2',
                      'fbx_import_scope':'exact-retained-key-windows-after-full-transform-admission'}.items():
        exact(spec.get(key),value,'candidate specification '+key)
    validate_runtime_grid(256)
    return spec


def validate_runtime_grid(subdivisions):
    require(type(subdivisions) is int and subdivisions in (128,256),'unsupported unchanged-budget runtime subdivision')
    keys=95*subdivisions+1;transforms=keys*75
    require(keys<=65536 and transforms<=2_000_000,'runtime decoder frame/transform cap exceeded')
    expected_bytes=1674+keys*(4+72*40+3*41)
    require(expected_bytes<=128*1024**2,'runtime format128MiB cap exceeded')
    values=np.asarray([i/(60*subdivisions) for i in range(keys)],dtype=np.float32)
    require(np.all(values[1:]>values[:-1]),'runtime float32 time collision')
    return {'keys':keys,'hz':60*subdivisions,'transforms':transforms,'expected_vra_bytes_if_metadata_unchanged':expected_bytes}


def validate_timing_policy(value):
    for key,expected in {'kind':'explicit-rational-resampling','subdivisions':SUBDIVISIONS,
                         'switches':[],'samples':RUNTIME_KEYS,'float32_collision_policy':'reject'}.items():
        exact(value.get(key),expected,'runtime timing policy '+key)
    validate_runtime_grid(SUBDIVISIONS)
    return value


def validate_runtime_times(values):
    expected=[float(np.float32(i/RUNTIME_HZ)) for i in range(RUNTIME_KEYS)]
    require(len(values)==RUNTIME_KEYS and all(type(v) is float and math.isfinite(v) for v in values),
            'runtime finite float32 time count/type differs')
    require(values==expected,'runtime24321 exact float32 key grid differs')
    require(all(b>a for a,b in zip(values,values[1:])),'runtime float32 key collision')
    return True


def candidate_spec():
    check_proof_root()
    return validate_spec(read(HERE/'candidate-spec.json'))


def candidate_identity():
    return {'proof_root':str(WORK.resolve()),'candidate_sha256':sha(HERE/'candidate.json'),
            'candidate_spec_sha256':sha(HERE/'candidate-spec.json'),'runtime_subdivisions':SUBDIVISIONS}


def validate_candidate(candidate,*,check_files=True):
    candidate_spec()
    for key,value in {'schema':CANDIDATE_SCHEMA,'state':'accepted','proof_root':str(WORK.resolve()),
                      'candidate_spec_sha256':sha(HERE/'candidate-spec.json'),'source_sha256':SOURCE_SHA,
                      'action':ACTION,'action_fingerprint':ACTION_SHA,'sample_grid_sha256':GRID_SHA,
                      'fbx_subdivisions':256,'runtime_subdivisions':256,'runtime_hz':15360,'runtime_keys':24321,
                      'thresholds':THRESHOLDS}.items():
        exact(candidate.get(key),value,'accepted candidate '+key)
    require(set(candidate.get('assets',{}))==set(ASSET_PATHS),'complete actual candidate asset pins required')
    for name,relative in ASSET_PATHS.items():
        record=candidate['assets'][name];expected=safe_output(relative).resolve()
        require(record.get('path')==str(expected),'candidate asset outside exact new-root layout')
        require(type(record.get('bytes')) is int and record['bytes']>0,'candidate actual byte count missing')
        value=record.get('sha256');require(isinstance(value,str) and len(value)==64 and value!='0'*64 and all(c in '0123456789abcdef' for c in value),'candidate actual asset hash missing/pending')
        if check_files:
            require(expected.is_file() and expected.stat().st_size==record['bytes'],'candidate asset missing/size differs')
            pin(expected,value)
    require(candidate.get('representation_passed') is True and candidate.get('processes_verified') is True,'candidate representation/process gate pending')
    require(candidate.get('runtime_complete') is False and candidate.get('runtime_activated') is False,'candidate admission cannot claim runtime completion or activation')
    require(candidate.get('evidence') and candidate.get('producer_files'),'candidate source evidence/pins missing')
    if check_files:
        for record in [*candidate['evidence'].values(),*candidate['producer_files'].values()]:
            path=Path(record['path']);require(path.is_file() and path.stat().st_size==record['bytes'],'candidate evidence missing/size differs');pin(path,record['sha256'])
    return candidate


def load_candidate():
    check_proof_root()
    path=HERE/'candidate.json'
    require(path.is_file(),'candidate is pending: actual export, focus and conversion pins must be admitted first')
    candidate=validate_candidate(read(path))
    from admit_candidate import validate_admitted
    return validate_admitted(candidate)


def validate_imported_key_grid(value):
    for field,expected in {'passed':True,'key_count':RUNTIME_KEYS,'subdivisions':SUBDIVISIONS,
                           'all_curves_checked':True,'preservation_patch_required_and_applied':True}.items():
        exact(value.get(field),expected,'FBX imported key grid '+field)
    expected=hashlib.sha256(np.asarray([1+i/SUBDIVISIONS for i in range(RUNTIME_KEYS)],dtype='<f4').tobytes()).hexdigest()
    require(value.get('native_frame_grid_sha256')==expected,'FBX preserved key times differ from exact256-grid')
    actions=value.get('actions')
    require(isinstance(actions,list) and len(actions)==6,'all six imported Actions must be key-grid checked')
    names=[row.get('action') for row in actions]
    require(all(isinstance(n,str) and n for n in names) and len(set(names))==6,'duplicate/missing imported Action identity')
    counts=[]
    for row in actions:
        require(row.get('frame_range')==[1,96],'imported Action frame range differs')
        count=row.get('curves');require(type(count) is int and count>0,'imported Action curves unmeasured');counts.append(count)
    require(type(value.get('curve_count')) is int and value['curve_count']==sum(counts),'imported curve coverage sum differs')
    return value

AUDITED_PATCHES={'blen_read_animations':'757bd21550d94e2190881ec6b0eb0ce80b275d2a230055cf7702044fe6dcc6e2',
                 'blen_store_keyframes_multi':'793a389ebde0e71ec3cec54e731c861753aa08015355904777a8c39b70da3a4e'}


def validate_patches(value):
    require(set(value)==set(AUDITED_PATCHES),'audited dense importer patch inventory differs')
    for name,expected in AUDITED_PATCHES.items():
        require(value[name].get('sha256')==expected and value[name].get('replacement_count')==1,'dense importer patch identity differs')
    require(value['blen_read_animations'].get('single_stack_binding_observer') is True,'observed exact Action binding required')


def validate_import_admission(value):
    validate_patches(value.get('patches',{}))
    single=value.get('single_stack_admission',{})
    for field,expected in {'schema':'rust-duty-fbx-single-stack/v1','logical_stack':ACTION,
                           'selection':'observed exact stack/layer/owner binding',
                           'action_name_matching':False,'renamed_actions':False}.items():
        exact(single.get(field),expected,'native single-stack '+field)
    require(type(single.get('stack_uuid')) is int and type(single.get('layer_uuid')) is int
            and isinstance(single.get('logical_layer'),str) and single['logical_layer'],'native observed stack/layer UUID absent')
    owners=('Arms',*ACTORS,'RD First Person Review')
    require(set(single.get('owners',{}))==set(owners) and set(single.get('owner_model_uuids',{}))==set(owners),'native stack owner coverage differs')
    for name in owners:
        row=single['owners'][name]
        require(row.get('bound_to_observed_action') is True and row.get('frame_range')==[1,96]
                and isinstance(row.get('action_name'),str) and row['action_name']
                and type(row.get('source_model_uuid')) is int
                and type(row.get('fcurves')) is int and row['fcurves']>0
                and row.get('source_model_uuid')==single['owner_model_uuids'][name],'native observed binding differs')
    return value


def validate_raw_key_grid(value):
    for key,expected in {'passed':True,'logical_stack':ACTION,'curve_count':1379,'key_count':24321,'subdivisions':256}.items():
        exact(value.get(key),expected,'raw FBX256 keygrid '+key)
    require(type(value.get('fbx_version')) is int and value['fbx_version']>0,'raw FBX version unmeasured')
    error=finite_number(value.get('maximum_native_frame_ktime_rounding'),'FBX integer tick rounding')
    require(0<=error<=2*60/46186158000,'FBX times differ beyond declared two-tick rounding')
    hashes=value.get('ktime_grid_hashes',{})
    require(isinstance(hashes,dict) and hashes and all(isinstance(k,str) and len(k)==64 and all(c in '0123456789abcdef' for c in k) and type(v) is int and v>0 for k,v in hashes.items()) and sum(hashes.values())==1379,'raw FBX clock hash coverage differs')
    return value
