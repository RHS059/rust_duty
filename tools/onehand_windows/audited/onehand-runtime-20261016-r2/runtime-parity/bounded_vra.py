"""Bounded read-only VRANIM01 admission, never animation sampling.

The pinned decoder's complete validity rules are retained, including every TRS,
visibility byte, clock, checksum and companion. Only metadata and times survive;
no Python copy of the complete animated transform table is constructed. Actual
pose/geometry sampling remains exclusively in the pinned Rust executable.
"""
from pathlib import Path
import math
import mmap
import struct
import zlib
from onehand_r2_common import G,require


def scan_buffer(data,*,vrs=None,vrm=None):
    decoder=G.vrview;header=decoder.HEADER
    require(header.size<=len(data)<=decoder.core.MAX_FILE,'VRA truncated or exceeds 128 MiB')
    magic,version,length,checksum,reserved=header.unpack_from(data)
    require(magic==decoder.MAGIC and version==decoder.VERSION,'invalid VRA magic/version')
    require(reserved==0 and length==len(data)-header.size,'invalid VRA header')
    view=memoryview(data)
    try:
        require(zlib.crc32(view[header.size:])==checksum,'VRA checksum mismatch')
        cursor=header.size
        def take(n):
            nonlocal cursor
            require(0<=n<=len(data)-cursor,'truncated VRA payload')
            start=cursor;cursor+=n
            return start
        def unpack(fmt):
            return struct.unpack_from(fmt,data,take(struct.calcsize(fmt)))
        def name():
            count,=unpack('<H');require(1<=count<=128,'invalid VRA string length')
            start=take(count)
            try:return decoder.string(bytes(view[start:start+count]).decode('utf-8'))
            except UnicodeDecodeError as exc:raise ValueError('invalid VRA UTF-8') from exc
        skin_crc,mesh_crc,bc=unpack('<III');require(1<=bc<=128,'bone count outside 1..128')
        bones=[(name(),unpack('<i')[0]) for _ in range(bc)]
        decoder.vrskin.validate_parents([b[1] for b in bones])
        ac,=unpack('<I');require(ac<=256,'actor count exceeds 256')
        actors=[];actor_names=set();assigned=set()
        for _ in range(ac):
            label=name();require(label not in actor_names,'duplicate actor name');actor_names.add(label)
            count,=unpack('<I');require(count<=256,'too many actor meshes');meshes=[]
            for _ in range(count):
                index,=unpack('<I');require(index<256 and index not in assigned,'invalid or duplicate actor mesh assignment')
                assigned.add(index);meshes.append(index)
            inverse=unpack('<16f');decoder.vrskin.matrix_valid(inverse,'actor inverse rest global')
            actors.append({'name':label,'meshes':meshes,'inverse_rest_global':inverse})
        cc,=unpack('<I');require(1<=cc<=128,'clip count outside 1..128')
        clips=[];names=set();total=0
        for _ in range(cc):
            label=name();require(label not in names,'duplicate clip name');names.add(label)
            flags,count=unpack('<II');require(flags<=1 and 1<=count<=65536,'invalid clip flags/frame count')
            total+=count*(bc+ac);require(total<=decoder.MAX_TRANSFORMS,'aggregate transform budget exceeded')
            require(count*(4+(bc+ac)*40+ac)<=len(data)-cursor,'truncated animation frames')
            frames=[];previous=-1
            for i in range(count):
                time_value,=unpack('<f')
                require(math.isfinite(time_value) and (time_value==0 if i==0 else time_value>previous),'invalid frame times')
                previous=time_value
                for _ in range(bc+ac):decoder.validate_transform(unpack('<10f'))
                start=take(ac);require(all(data[j] in (0,1) for j in range(start,start+ac)),'invalid visibility')
                frames.append({'time':time_value})
            clips.append({'name':label,'loop':bool(flags),'frames':frames})
        require(cursor==len(data),'trailing VRA payload bytes')
        if vrs is not None:
            decoder.validation_memo.validated(decoder.vrskin.inspect_vrs,vrs)
            require(zlib.crc32(vrs)==skin_crc,'VRS companion checksum mismatch')
            offset=28;actual=[];count=struct.unpack_from('<I',vrs,24)[0]
            for _ in range(count):
                size=struct.unpack_from('<H',vrs,offset)[0];offset+=2
                label=vrs[offset:offset+size].decode();offset+=size
                parent=struct.unpack_from('<i',vrs,offset)[0];offset+=132
                actual.append((label,parent))
            require(actual==bones,'VRS companion skeleton mismatch')
        if vrm is not None:
            info=decoder.validation_memo.validated(decoder.core.inspect_vrm,vrm)
            require(zlib.crc32(vrm)==mesh_crc,'VRM companion checksum mismatch')
            require(assigned==set(range(info['meshes'])),'rigid companion meshes must be assigned exactly once')
        return {'bones':bones,'actors':actors,'clips':clips,'skin_crc':skin_crc,'mesh_crc':mesh_crc}
    finally:
        view.release()


def scan_vra(path,*,vrs=None,vrm=None):
    path=Path(path)
    require(G.vrview.HEADER.size<=path.stat().st_size<=G.vrview.core.MAX_FILE,'VRA truncated or exceeds 128 MiB')
    with path.open('rb') as stream:
        with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            return scan_buffer(data,vrs=vrs,vrm=vrm)


def metadata_only(decoded):
    """Test/reference projection; never performs interpolation or sampling."""
    return {**{name:decoded[name] for name in ('bones','actors','skin_crc','mesh_crc')},
            'clips':[{'name':c['name'],'loop':c['loop'],'frames':[{'time':f['time']} for f in c['frames']]} for c in decoded['clips']]}
