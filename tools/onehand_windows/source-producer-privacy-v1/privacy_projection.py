"""Closed metadata-comment projection. No native IO or historical resampling.

The original full metadata digest cannot determine the projected digest. Native
replay derives expected metadata from the exact baseline in memory, then compares
the created Action and its fresh reopen to that expected value. Only its digest
leaves the native replay. Unknown inherited values are never serialized here.
"""
import copy,hashlib,json
from pathlib import Path

OMITTED = ('acceptance','acceptance_status','animated_control','compensation_model',
           'hand_contact_status','hidden_motion_inference_scope','known_residuals',
           'reconstruction_status','render_status')
RETAINED = ('base_action','baseline_action_count','baseline_sha256',
            'hidden_motion_inferred','source_end_frame','source_range_convention','source_start_frame')
SCHEMA = 'rust-duty-onehand-v6-comment-projected-delta/v1'
META_SCHEMA = 'rust-duty-onehand-comment-projected-metadata/v1'
RELATION_SCHEMA = 'rust-duty-onehand-metadata-projection-binding/v1'
SOURCE_RELATION = 'exact authored motion and structured state; explicit nine-key comment exclusion'
HERE = Path(__file__).absolute().parent

def require(ok,message):
    if not ok:raise ValueError(message)

def digest(value):
    # Exactly the source producer's established metadata representation.
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def strict(raw):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'duplicate JSON field');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def pinned_json(path,expected,cap):
    with Path(path).open('rb') as f:raw=f.read(cap+1)
    require(len(raw)<=cap,'bounded JSON required')
    require(hashlib.sha256(raw).hexdigest()==expected,'same-buffer JSON pin differs')
    return strict(raw)

def manifest():
    # This manifest is part of the independently pinned source package. Native
    # replay also includes it in producer_hashes; no self-declared external pin.
    with (HERE/'PROJECTION.json').open('rb') as f:raw=f.read(65537)
    require(len(raw)<=65536,'projection manifest bound')
    value=strict(raw)
    require(value['schema']=='rust-duty-onehand-comment-projection/v1','projection schema')
    require(value['omitted_keys']==list(OMITTED) and value['retained_keys']==list(RETAINED),'closed projection inventory')
    return value,hashlib.sha256(raw).hexdigest()

def validate_metadata(patch):
    m,_=manifest()
    require(type(patch) is dict and set(patch)=={'schema','before_sha256','after_sha256','properties','remove_properties','use_fake_user'},'projected metadata fields')
    require(patch['schema']==META_SCHEMA and patch['after_sha256'] is None,'projected metadata uses native-derived full identity')
    require(patch['before_sha256']==m['original_metadata_before_sha256'] and patch['use_fake_user']==m['use_fake_user_operation'],'metadata baseline/settings identity')
    require(type(patch['properties']) is dict and set(patch['properties'])==set(RETAINED),'exact seven retained operations required')
    require(type(patch['remove_properties']) is dict and set(patch['remove_properties'])==set(OMITTED),'all nine explicit removals required')
    for k in RETAINED:
        row=patch['properties'][k];want=m['retained_operations'][k]
        require(type(row) is dict and set(row)=={'before_sha256','value'},'retained operation fields')
        require(row['before_sha256']==want['before_sha256'] and type(row['value']).__name__==want['value_type'] and digest(row['value'])==want['value_sha256'],'retained operation identity differs')
    for k in OMITTED:
        require(patch['remove_properties'][k]=={'before_sha256':m['omitted_operations'][k]['before_sha256']},'removal baseline precondition differs')
    require(digest(patch)==m['metadata_recipe_sha256'],'metadata construction identity differs')
    return patch

def apply(base,patch):
    validate_metadata(patch)
    require(type(base) is dict and set(base)=={'use_fake_user','properties'} and type(base['use_fake_user']) is bool and type(base['properties']) is dict,'baseline metadata inventory')
    require(digest(base)==patch['before_sha256'],'full baseline metadata differs')
    out=copy.deepcopy(base)
    for k in (*RETAINED,*OMITTED):
        row=patch['properties'][k] if k in RETAINED else patch['remove_properties'][k]
        actual=digest(base['properties'][k]) if k in base['properties'] else None
        require(actual==row['before_sha256'],'metadata operation baseline precondition differs')
    for k in OMITTED:out['properties'].pop(k,None)
    for k in RETAINED:out['properties'][k]=patch['properties'][k]['value']
    if patch['use_fake_user'] is not None:out['use_fake_user']=patch['use_fake_user']
    require(set(out['properties'])==(set(base['properties'])-set(OMITTED))|set(RETAINED),'projected complete property inventory differs')
    require(not set(OMITTED)&set(out['properties']),'omitted comment survived')
    return out

def preserved_recipe(recipe):
    return {k:v for k,v in recipe.items() if k not in ('schema','scope','metadata','producer_sha256','privacy_projection_sha256')}

def validate_recipe(recipe):
    m,sha=manifest()
    require(recipe['privacy_projection_sha256']==sha and recipe['schema']==SCHEMA,'projected delta relation differs')
    require(recipe['scope']==SOURCE_RELATION,'projected scope differs')
    require(digest(preserved_recipe(recipe))==m['preserved_recipe_sha256'],'motion/static/auxiliary/clock/lineage recipe changed')
    validate_metadata(recipe['metadata'])

def binding(projected_metadata_sha256):
    m,sha=manifest()
    require(type(projected_metadata_sha256) is str and len(projected_metadata_sha256)==64 and all(c in '0123456789abcdef' for c in projected_metadata_sha256),'actual projected full metadata digest required')
    return {'schema':RELATION_SCHEMA,'projection_sha256':sha,
            'original_delta_sha256':m['original_delta']['sha256'],
            'original_metadata_sha256':m['original_metadata_after_sha256'],
            'metadata_recipe_sha256':m['metadata_recipe_sha256'],
            'projected_metadata_sha256':projected_metadata_sha256,
            'omitted_keys':list(OMITTED),'historical_reference_resampled':False}

def validate_binding(value,projected_metadata_sha256):
    require(type(value) is dict and digest(value)==digest(binding(projected_metadata_sha256)),'projection binding differs')

def historical_expectations(recipe):
    """Hash-only expected envelopes, explicitly not an original recipe replica."""
    validate_recipe(recipe);m,_=manifest()
    return {'action':recipe['action'],'action_auxiliary_sha256':recipe['action_auxiliary_sha256'],
            'metadata':{'after_sha256':m['original_metadata_after_sha256']},
            'inherited_actions':recipe['inherited_actions'],
            'approved_static_hashes':recipe['approved_static_hashes'],
            'producer_sha256':m['original_producer_sha256']}


def verify_actual(actual,expected):
    require(digest(actual)==digest(expected),'full projected metadata differs from independently constructed expectation')
    require(type(actual) is dict and set(actual)=={'use_fake_user','properties'},'actual metadata fields')
    require(set(actual['properties'])==set(expected['properties']),'actual full property inventory differs')
    require(not set(OMITTED)&set(actual['properties']),'omitted key survived actual replay')
    return digest(actual)
