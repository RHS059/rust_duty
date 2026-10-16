"""Byte-exact full evaluated rigid geometry, including signed-zero coordinates."""
from dataclasses import dataclass
import hashlib
import numpy as np


@dataclass(frozen=True)
class GeometryBytes:
    vertex_count: int
    polygon_count: int
    loop_count: int
    vertices: bytes
    starts: bytes
    sizes: bytes
    indices: bytes
    def polygons(self):
        starts=np.frombuffer(self.starts,dtype='<i8')
        sizes=np.frombuffer(self.sizes,dtype='<i8')
        indices=np.frombuffer(self.indices,dtype='<i8')
        return [indices[start:start+size].tolist() for start,size in zip(starts,sizes)]
    def digests(self):
        return {'float64_le_vertices_sha256':hashlib.sha256(self.vertices).hexdigest(),
                'int64_le_topology_sha256':hashlib.sha256(self.starts+self.sizes+self.indices).hexdigest()}


def canonical_buffers(vertices,starts,sizes,indices):
    vertices=np.asarray(vertices,dtype='<f8',order='C')
    if vertices.ndim!=2 or vertices.shape[1]!=3 or len(vertices)==0 or not np.isfinite(vertices).all():
        raise ValueError('invalid/nonfinite rigid coordinates')
    values=[]
    for original in (starts,sizes,indices):
        array=np.asarray(original)
        if array.ndim!=1 or array.dtype.kind not in 'iu' or (array<0).any() or (array>2**62).any():
            raise ValueError('invalid rigid integer topology')
        values.append(np.asarray(array,dtype='<i8',order='C'))
    starts,sizes,indices=values
    if len(starts)==0 or len(starts)!=len(sizes) or (sizes<3).any() or len(indices)==0:
        raise ValueError('invalid rigid polygon layout')
    expected=np.concatenate((np.array([0],dtype='<i8'),np.cumsum(sizes[:-1],dtype='<i8')))
    if not np.array_equal(starts,expected) or int(sizes.sum())!=len(indices) or (indices>=len(vertices)).any():
        raise ValueError('invalid rigid loop/index coverage')
    return GeometryBytes(len(vertices),len(starts),len(indices),vertices.tobytes(order='C'),
                         starts.tobytes(order='C'),sizes.tobytes(order='C'),indices.tobytes(order='C'))
