"""Reproduce public projected bytes from the one exact private original in memory.

Caller supplies at most32MiB; this module does not open/read a BLEND, write raw
JSON, invoke Blender, or publish. The omitted values are never returned/reported.
"""
import copy,hashlib,json
import privacy_projection as p
import onehand_v6_source_native as native

def project_bytes(original_raw):
 m,projection_sha=p.manifest()
 p.require(type(original_raw) is bytes and len(original_raw)<=32*1024**2,'bounded original bytes required')
 p.require({'sha256':hashlib.sha256(original_raw).hexdigest(),'bytes':len(original_raw)}==m['original_delta'],'exact original delta bytes required')
 original=p.strict(original_raw)
 p.require(set(original['metadata']['properties'])==set(p.OMITTED)|set(p.RETAINED),'original changed-property inventory differs')
 p.require(p.digest(original['metadata'])==m['original_metadata_patch_sha256'],'original metadata delta differs')
 p.require(original['producer_sha256']==m['original_producer_sha256'],'original source producer differs')
 metadata={'schema':p.META_SCHEMA,'before_sha256':original['metadata']['before_sha256'],'after_sha256':None,
           'properties':{k:original['metadata']['properties'][k] for k in p.RETAINED},
           'remove_properties':{k:{'before_sha256':original['metadata']['properties'][k]['before_sha256']} for k in p.OMITTED},
           'use_fake_user':original['metadata']['use_fake_user']}
 result=copy.deepcopy(original)
 result.update(schema=p.SCHEMA,scope=p.SOURCE_RELATION,metadata=metadata,
               privacy_projection_sha256=projection_sha,producer_sha256=native.producer_hashes())
 native.validate_recipe(result)
 p.require(p.preserved_recipe(result)==p.preserved_recipe(original),'unchanged authored data differs')
 return (json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
