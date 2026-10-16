"""Small source-side rigid witnesses; no runtime-derived expected geometry."""
import hashlib
import json
import math


def geometry_record(vertices, polygons):
    if not vertices or any(len(v)!=3 or any(not math.isfinite(c) for c in v) for v in vertices):
        raise ValueError('invalid/empty rigid local vertices')
    if not polygons or any(len(p)<3 or any(type(i) is not int or i<0 or i>=len(vertices) for i in p)
                           for p in polygons):
        raise ValueError('invalid/empty rigid polygons')
    content={'vertices_local':vertices,'polygons':polygons}
    encoded=json.dumps(content,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return {**content,'vertex_count':len(vertices),'polygon_count':len(polygons),
            'geometry_sha256':hashlib.sha256(encoded).hexdigest()}
