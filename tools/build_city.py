#!/usr/bin/env python3
"""Deterministically assemble Cedar Junction from the pinned low_poly_items pack.
Run: python tools/build_city.py --source ../low_poly_items
Requires numpy. Runtime files contain actual source mesh geometry, not proxies.
"""
import argparse, gzip, hashlib, json, math, struct
from dataclasses import dataclass
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
SOURCE_COMMIT='3a87b1f2611c56fcfbfc7b39adaf914ab5359446'
DEFAULT_OUT = ROOT / 'assets/levels/cedar_junction'
# Reviewed small dressing props only. Architecture, streets, and unknown assets
# retain their full world draw distance; geometry size is never a proxy for LOD.
SMALL_PROP_ASSETS = frozenset({
    'b16_baguette_in_paper_sleeve', 'b16_fluted_paper_plate',
    'b16_folded_newspaper', 'b16_gable_top_milk_carton',
    'b16_juice_box_with_straw', 'b16_ribbed_water_bottle',
    'b16_sealed_potato_chip_bag', 'b16_six_egg_carton',
    'b16_square_juice_bottle', 'b16_takeaway_coffee_cup',
    'b17_baseball_fielders_glove', 'b17_folded_picnic_blanket',
    'b17_handheld_torch_flashlight', 'b17_laced_american_football',
    'b17_outdoor_two_way_radio', 'b17_ribbed_rolling_suitcase',
    'b17_seamed_basketball', 'b17_stitched_baseball',
    'b17_vented_bicycle_helmet', 'b17_zippered_day_backpack',
})


@dataclass
class CityPart:
    vertices: np.ndarray
    indices: np.ndarray
    metadata: dict


def glb_mesh(path):
    data=path.read_bytes(); off=12; doc=None; binary=None
    assert data[:4]==b'glTF'
    while off<len(data):
        n,kind=struct.unpack_from('<II',data,off);off+=8
        chunk=data[off:off+n];off+=n
        if kind==0x4e4f534a:doc=json.loads(chunk)
        if kind==0x004e4942:binary=chunk
    def acc(i):
        a=doc['accessors'][i];v=doc['bufferViews'][a['bufferView']]
        dtype={5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[a['componentType']]
        width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
        return np.ndarray((a['count'],width),dtype=dtype,buffer=binary,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',np.dtype(dtype).itemsize*width),np.dtype(dtype).itemsize)).copy()
    verts=[];indices=[];count=0
    for mesh in doc['meshes']:
        for p in mesh['primitives']:
            pos=acc(p['attributes']['POSITION']);norm=acc(p['attributes']['NORMAL'])
            color=doc['materials'][p['material']]['pbrMetallicRoughness'].get('baseColorFactor',[1,1,1,1])
            # Source factors are linear; framebuffer facade uses display-space vertex colors.
            rgb=np.array(color[:3]);rgb=np.where(rgb<=.0031308,rgb*12.92,1.055*rgb**(1/2.4)-.055)
            col=np.tile([*rgb,1.],(len(pos),1));verts.append(np.column_stack((pos,norm,col)))
            # Widen before adding the primitive offset: u16 arithmetic can wrap.
            indices.append(acc(p['indices']).ravel().astype(np.uint32)+count);count+=len(pos)
    return np.concatenate(verts).astype('<f4'),np.concatenate(indices).astype(np.uint32)

class City:
    def __init__(self,source):
        self.source=source;self.meshes={};self.parts=[];self.instances=[];self.colliders=[];self.buildings=[]
        self.catalog={x['name']:x for x in json.loads((source/'manifest.json').read_text())['assets']}
    def collision(self,label,lo,hi):
        self.colliders.append({'label':label,'min':list(map(float,lo)),'max':list(map(float,hi)),'kind':0})
    def add_part(self, vertices, indices, asset, building=None, max_distance=0.):
        metadata = {'id': len(self.parts), 'asset': asset, 'max_distance': max_distance}
        if building is not None:
            metadata['building'] = building
        self.parts.append(CityPart(vertices, indices, metadata))
        return metadata

    def asset(self,id,x,y,z,yaw=0,scale=(1,1,1),collider=False,*,building=None):
        if id not in self.meshes:self.meshes[id]=glb_mesh(self.source/self.catalog[id]['glb'])
        v,ind=self.meshes[id];v=v.copy();a=math.radians(yaw);c,s=math.cos(a),math.sin(a)
        rot=np.array([[c,0,s],[0,1,0],[-s,0,c]])
        v[:,:3]=(v[:,:3]*scale)@rot.T+np.array([x,y,z]);v[:,3:6]=(v[:,3:6]/scale)@rot.T
        v[:,3:6]/=np.maximum(np.linalg.norm(v[:,3:6],axis=1,keepdims=True),1e-12)
        metadata = self.add_part(v, ind, id, building, 120. if id in SMALL_PROP_ASSETS else 0.)
        self.instances.append({**metadata, 'position':[x,y,z], 'yaw':yaw, 'scale':list(scale)})
        if collider:self.collision(id,v[:,:3].min(axis=0),v[:,:3].max(axis=0))
    def box(self,label,center,size,color,solid=True,*,building=None):
        center=np.array(center);size=np.array(size);v=[];inds=[]
        if label.startswith("COLLIDER::"):
            if solid:self.collision(label,center-size/2,center+size/2)
            return
        for normal,u,w in [((1,0,0),(0,1,0),(0,0,1)),((-1,0,0),(0,0,1),(0,1,0)),((0,1,0),(0,0,1),(1,0,0)),((0,-1,0),(1,0,0),(0,0,1)),((0,0,1),(1,0,0),(0,1,0)),((0,0,-1),(0,1,0),(1,0,0))]:
            start=len(v);normal=np.array(normal);u=np.array(u);w=np.array(w)
            for a,b in [(-1,-1),(1,-1),(1,1),(-1,1)]:
                p=center+(normal+a*u+b*w)*size*.5;v.append([*p,*normal,*color[:3],1])
            inds.extend([start,start+1,start+2,start,start+2,start+3])
        self.add_part(np.array(v,dtype='<f4'),np.array(inds,dtype=np.uint32),label,building)
        if solid:self.collision(label,center-size/2,center+size/2)
    def write(self,out,*,write_source_lock=None):
        """Write complete authored parts, never bucket/merge or narrow indices.

        Alternate output directories leave the tracked provenance lock alone by
        default. Production output retains the existing source-lock update.
        """
        out = Path(out)
        if write_source_lock is None:
            write_source_lock = out.resolve() == DEFAULT_OUT.resolve()
        metadata = json.dumps([part.metadata for part in self.parts],
                              separators=(',', ':'), allow_nan=False).encode('utf-8')
        if not 0 < len(self.parts) <= 262144 or len(metadata) > 32 * 1024**2:
            raise ValueError('city instance count/metadata outside format limits')
        decoded_bytes = 20 + len(metadata)
        for part in self.parts:
            v, i = part.vertices, part.indices
            if (v.ndim != 2 or v.shape[1] != 10 or not 0 < len(v) <= 4_000_000
                    or i.ndim != 1 or not 0 < len(i) <= 12_000_000 or len(i) % 3
                    or not np.issubdtype(i.dtype, np.integer)
                    or i.min() < 0 or i.max() >= len(v)):
                raise ValueError('invalid city instance geometry')
            decoded_bytes += 32 + len(v) * 40 + len(i) * 4
        if decoded_bytes > 768 * 1024**2:
            raise ValueError('city instance geometry exceeds file limit')
        out.mkdir(parents=True,exist_ok=True)
        with (out/'meshes.bin.tmp').open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as f:
            f.write(b'RDCITY04')
            f.write(struct.pack('<II', 0, len(metadata)))
            f.write(metadata)
            f.write(struct.pack('<I', len(self.parts)))
            for part in self.parts:
                v, i = part.vertices, part.indices
                f.write(struct.pack('<6fII',*v[:,:3].min(axis=0),*v[:,:3].max(axis=0),len(v),len(i)))
                f.write(v.astype('<f4').tobytes())
                f.write(i.astype('<u4').tobytes())
        (out/'meshes.bin.tmp').replace(out/'meshes.bin')
        level={'schema':'rust-duty-city/v1','name':'Cedar Junction','geometry_format':'RDCITY04','mesh_file':'meshes.bin','spawn':{'position':[0,0,38],'yaw_degrees':-90},'supply_position':[8,.15,38], 'bounds':{'min':[-110,-1,-110],'max':[110,20,110]},'colliders':self.colliders,'buildings':self.buildings,'landmarks':[{'name':'Cedar Commons','position':[86,.15,32]},{'name':'Municipal parking','position':[-86,.15,32]},{'name':'Market Square','position':[32,.15,86]}], 'statistics':{'buildings':len(self.buildings),'asset_instances':len(self.instances),'unique_assets':len(self.meshes),'render_chunks':len(self.parts),'vertices':sum(len(p.vertices) for p in self.parts),'triangles':sum(len(p.indices)//3 for p in self.parts),'colliders':len(self.colliders)},'mesh_sha256':hashlib.sha256((out/'meshes.bin').read_bytes()).hexdigest()}
        (out/'level.json').write_text(json.dumps(level,indent=2)+'\n')
        (out/'layout.json').write_text(json.dumps({'instances':self.instances,'buildings':self.buildings},indent=2)+'\n')
        if write_source_lock:
            lock={'repository':'RHS059/low_poly_items','commit':SOURCE_COMMIT,'coordinate_system':'Y up; meters; glTF coordinates preserved','assets':[{'id':id,'path':self.catalog[id]['glb'],'sha256':hashlib.sha256((self.source/self.catalog[id]['glb']).read_bytes()).hexdigest()} for id in sorted(self.meshes)]}
            (ROOT/'tools/city_source_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
        print(json.dumps(level['statistics'],indent=2))

def streets(c):
    asphalt=(.23,.25,.26);concrete=(.66,.65,.59);paint=(.9,.84,.62)
    c.box('ground',(0,-.3,0),(220,.6,220),(.37,.43,.30))
    for x in [-64,0,64]:
        c.box('north-south avenue',(x,.007,0),(12,.014,216),asphalt,False)
        for lo,hi in [(-108,-70),(-58,-6),(6,58),(70,108)]:
            for side in [-1,1]:c.box('sidewalk',(x+side*8,.075,(lo+hi)/2),(4,.15,hi-lo),concrete)
    for z in [-64,0,64]:
        c.box('east-west street',(0,.016,z),(216,.016,12),asphalt,False)
        # Keep intersections level; sidewalks terminate at avenue crossings.
        for lo,hi in [(-108,-74),(-54,-10),(10,54),(74,108)]:
            for side in [-1,1]:c.box('sidewalk',((lo+hi)/2,.075,z+side*8),(hi-lo,.15,4),concrete)
    for x in [-64,0,64]:
        for z in range(-102,106,6):
            if min(abs(z-k) for k in [-64,0,64])<11:continue
            for dx in [-.16,.16]:c.box('double yellow',(x+dx,.031,z),(.09,.01,3),paint,False)
    for z in [-64,0,64]:
        for x in range(-102,106,6):
            if min(abs(x-k) for k in [-64,0,64])<11:continue
            for dz in [-.16,.16]:c.box('double yellow',(x,.032,z+dz),(3,.01,.09),paint,False)
    for x in [-64,0,64]:
        for z in [-64,0,64]:
            for d in [-8,8]:
                for t in [-4,-2,0,2,4]:
                    c.box('crosswalk',(x+t,.038,z+d),(1,.01,2.4),(.86,.85,.76),False)
                    c.box('crosswalk',(x+d,.039,z+t),(2.4,.01,1),(.86,.85,.76),False)
            c.asset('b02_street_name_pair',x+9,.15,z+9)
            c.asset('b02_stop_sign',x-7,.15,z+10,yaw=180)
            c.asset('b02_stop_sign',x+7,.15,z-10)
    for x in [-64,0,64]:
        for z in [-92,-44,-20,20,44,92]:
            c.asset('b18_tapered_lantern_avenue_lamp',x+8.8,.15,z)
            if abs(z)<60:
                c.asset('b08_staked_young_street_tree',x-8.7,.15,z)
                c.asset('b05_classic_fire_hydrant',x+7.2,.15,z+5)
    # Alleys connect all four blocks and provide rear approach routes.
    for x in [-32,32]:c.box('service alley',(x,.028,0),(5,.015,106),(.36,.36,.34),False)
    for z in [-32,32]:c.box('service alley',(0,.029,z),(106,.015,5),(.36,.36,.34),False)
    for x in [-108,108]:c.box('perimeter stone wall',(x,1.2,0),(.6,2.4,216),(.43,.43,.39))
    for z in [-108,108]:c.box('perimeter stone wall',(0,1.2,z),(216,2.4,.6),(.43,.43,.39))

def dressing(c):
    cars=['b03_midsize_sedan','b03_classic_muscle_coupe','b03_compact_station_wagon','b03_family_minivan','b03_regular_cab_work_pickup','b03_three_row_family_suv','b03_three_door_city_hatchback']
    for i,(x,z) in enumerate([(s*4.4,z) for s in [-1,1] for z in [-44,-24,22,43]]+[(x,59.5) for x in [-42,-22,20,42]]):
        c.asset(cars[i%len(cars)],x,.03,z,yaw=(0 if z==59.5 else 90),collider=True)
    c.asset('b15_low_floor_transit_bus',-60,.025,30,yaw=90,collider=True)
    c.asset('b01_glass_flat_roof_bus_shelter',-55,.15,30,yaw=90)
    c.asset('b02_bus_stop_sign',-56,.15,35)
    c.asset('b15_parcel_step_van',32,.03,-40,yaw=90,collider=True)
    for x in [-32,32]:
        for z in [-48,-16,16,48]:
            c.asset('b04_front_load_commercial_dumpster',x+3,.03,z,yaw=90,collider=True)
            c.asset('b14_pallet_carton_stack',x-3,.03,z+2,collider=True)
    for z in [-64,0,64]:
        for x in [-44,-20,20,44]:
            c.asset('b01_cast_iron_park_bench',x,.15,z+8.5)
            c.asset('b02_single_parking_meter',x+3,.15,z+7)
    # Cedar Commons: a neighborhood park, court and picnic grove.
    c.box('park lawn',(87,.08,32),(34,.16,48),(.42,.51,.32))
    c.box('park promenade',(86,.17,32),(3,.05,48),(.71,.67,.57))
    c.box('cross path',(86,.171,32),(34,.05,3),(.71,.67,.57))
    for x,z in [(74,13),(100,13),(74,50),(100,50),(99,36),(74,37)]:
        c.asset('b08_sugar_maple' if z%2 else 'b08_american_elm',x,.16,z)
        # Trunk-only collision preserves walkable space beneath the canopy.
        c.box('COLLIDER::tree trunk',(x,1,z),(.55,2,.55),(.32,.25,.18))
    for x,z in [(78,20),(97,20),(78,43),(97,43)]:c.asset('b01_classic_aframe_picnic_table',x,.16,z,collider=True)
    c.asset('b09_double_swing',96,.16,47)
    c.asset('b09_roofed_play_tower',94,.16,10)
    c.asset('b01_stone_spout_fountain',86,.20,32,collider=True)
    for z in [23,40]:c.asset('b01_memorial_wood_bench',89,.2,z,yaw=90)
    # Parking west of downtown, individual bays and a public pay point.
    c.box('parking lot',(-86,.018,32),(32,.02,48),(.25,.27,.27),False)
    for side in [-1,1]:
        for i in range(7):
            z=13+i*6;c.box('parking stripe',(-86+side*9,.041,z),(6,.01,.1),(.83,.82,.73),False)
            if i%3!=1:c.asset(cars[(i+side)%len(cars)],-86+side*9,.03,z+2.9,yaw=0,collider=True)
    c.asset('b02_parking_pay_station',-74,.03,54)
    c.asset('b02_public_parking_sign',-73,.03,10)
    c.asset('b18_twin_shoebox_parking_lamp',-86,.03,32)
    # Saturday market plaza, walk-through aisles and café seating.
    c.box('market paving',(32,.075,86),(48,.15,32),(.66,.60,.49))
    for i,x in enumerate([14,23,32,41,50]):
        c.asset('b10_farmers_market_canvas_stall',x,.15,96)
        c.asset('b10_tiered_sidewalk_produce_stand',x,.15,93,collider=True)
    for x in [20,32,44]:
        c.asset('b10_square_cafe_umbrella_table',x,.15,81,collider=True)
        for d in [-1,1]:c.asset('b10_woven_metal_cafe_chair',x+d*1.4,.15,81,yaw=90*d)
    c.asset('b10_hot_dog_pushcart',13,.15,79,collider=True)
    c.asset('b14_postal_collection_drop_box',10,.15,72)
    # Recreation and municipal service lots complete the outer urban blocks.
    c.box('basketball court',(-86,.045,-32),(24,.09,32),(.29,.39,.36))
    for x in [-97,-75]:c.box('court sideline',(x,.095,-32),(.12,.012,29),(.88,.85,.72),False)
    for z in [-46,-18,-32]:c.box('court line',(-86,.095,z),(22,.012,.12),(.88,.85,.72),False)
    c.asset('b09_basketball_gooseneck_pole',-86,.09,-46,collider=True)
    c.asset('b09_basketball_gooseneck_pole',-86,.09,-18,yaw=180,collider=True)
    c.asset('b09_four_row_bleachers',-102,.03,-32,yaw=90,collider=True)
    c.box('municipal service yard',(86,.022,-32),(32,.025,44),(.38,.37,.33),False)
    c.asset('b14_twenty_foot_freight_container',94,.035,-45,collider=True)
    c.asset('b15_municipal_dump_truck',84,.035,-40,yaw=90,collider=True)
    c.asset('b15_bucket_utility_truck',96,.035,-27,yaw=90,collider=True)
    for z in [-48,-20]:c.asset('b14_pallet_lumber_bundle',76,.035,z,collider=True)
    for x in [75,82,89,96]:c.asset('b02_concrete_jersey_barrier',x,.035,-12)
    # A public garden occupies the northern fringe.
    for x in [-44,-32,-20,20,32,44]:
        c.asset('b08_raised_perennial_bed',x,0,-86)
        c.asset('b01_classic_aframe_picnic_table',x,0,-95,collider=True)
        c.asset('b08_flowering_cherry',x,0,-76)
    # Perimeter planting frames the district instead of an empty horizon.
    for x in range(-96,105,16):
        for z in [-101,103]:c.asset('b08_eastern_white_pine',x,0,z)
    for z in range(-84,92,16):
        for x in [-102,103]:c.asset('b08_honeylocust',x,0,z)

def signage(c):
    from PIL import Image, ImageDraw, ImageFont
    font=ImageFont.load_default()
    for building in c.buildings:
        for sign in building.get('signs',[]):
            text=sign['text'].upper(); bounds=font.getbbox(text)
            mask=Image.new('L',(bounds[2]+2,12));ImageDraw.Draw(mask).text((1,-bounds[1]),text,font=font,fill=255)
            a=np.array(mask);ys,xs=np.where(a>128)
            if not len(xs):continue
            a=a[ys.min():ys.max()+1,xs.min():xs.max()+1]
            unit=min(sign['height']/a.shape[0],sign['width']/a.shape[1]);x,y,z=sign['position'];flip=-1 if sign['yaw'] else 1
            for row in range(a.shape[0]):
                col=0
                while col<a.shape[1]:
                    if a[row,col]<=128:col+=1;continue
                    end=col+1
                    while end<a.shape[1] and a[row,end]>128:end+=1
                    dx=((col+end)/2-a.shape[1]/2)*unit
                    c.box('store lettering',(x-flip*dx,y+(a.shape[0]/2-row-.5)*unit,z-flip*.013),((end-col)*unit,unit,.016),(.94,.89,.72),False,building=building['id'])
                    col=end

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=DEFAULT_OUT,
                    help='Output directory; defaults to the production city assets')
    ap.add_argument('--write-source-lock',action=argparse.BooleanOptionalAction,default=None,
                    help='Update tracked provenance lock (default: only for production --out)')
    args=ap.parse_args()
    c=City(args.source);streets(c)
    from city_buildings import build
    build(c.asset,c.box,c.buildings);dressing(c);signage(c)
    c.write(args.out,write_source_lock=args.write_source_lock)
if __name__=='__main__':main()
