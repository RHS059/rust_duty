#!/usr/bin/env python3
"""Original synthetic animation/compiler tests. No licensed master is accessed."""
import copy
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import make_skin_fixture
import vrpack
import vrskin
import vrview


def glb(doc,blob):
    raw=json.dumps(doc,separators=(',',':')).encode(); raw+=b' '*(-len(raw)%4)
    blob=bytes(blob)+b'\0'*(-len(blob)%4)
    return struct.pack('<4sII',b'glTF',2,28+len(raw)+len(blob))+struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(blob),0x004e4942)+blob


def fixture():
    raw,_=make_skin_fixture.build(); doc,old=vrpack.parse_glb(raw)
    blob=bytearray(old[:doc['buffers'][0]['byteLength']])
    def acc(fmt,rows,kind):
        blob.extend(b'\0'*(-len(blob)%4)); offset=len(blob)
        for row in rows: blob.extend(struct.pack('<'+fmt,*row))
        doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(blob)-offset})
        doc['accessors'].append({'bufferView':len(doc['bufferViews'])-1,'componentType':5126,'count':len(rows),'type':kind})
        doc['buffers'][0]['byteLength']=len(blob); return len(doc['accessors'])-1
    attrs=doc['meshes'][0]['primitives'][0]['attributes']
    doc['meshes'].append({'primitives':[{'attributes':{k:v for k,v in attrs.items() if k in ('POSITION','NORMAL','TEXCOORD_0')},'indices':5}]})
    doc['nodes'].append({'name':'gun','mesh':1,'translation':[0,0,2]})
    doc['nodes'][0]['children'].append(5)
    inp=acc('f',[(0,),(1,)],'SCALAR')
    out=acc('3f',[(2,0,0),(4,0,0)],'VEC3')
    turn=acc('4f',[(0,0,0,1),(0,0,1,0)],'VEC4')
    doc['animations']=[{'samplers':[{'input':inp,'output':out,'interpolation':'LINEAR'}, {'input':inp,'output':turn,'interpolation':'LINEAR'}],
                        'channels':[{'sampler':0,'target':{'node':0,'path':'translation'}},{'sampler':1,'target':{'node':5,'path':'rotation'}}]}]
    return doc,bytes(blob),acc


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.doc,self.blob,_=fixture()

    def scene(self): return vrview.Scene(self.doc,self.blob)

    def pack(self,loop=False):
        scene=self.scene(); vrs,vrm,actors=scene.companions(['gun']); frames=[]
        for t in (0.,1.):
            bones,gs=scene.sample(t)
            frames.append({'time':t,'bones':bones,'actors':[vrview.decompose(gs[5])],'visible':[int(t==0)]})
        clips=[{'name':'release','loop':loop,'frames':frames}]
        return vrview.encode_vra(scene.skin.bones,actors,clips,vrs,vrm),vrs,vrm

    def patch(self,data,offset,fmt,*values):
        data=bytearray(data); struct.pack_into('<'+fmt,data,offset,*values)
        struct.pack_into('<I',data,16,zlib.crc32(data[24:])); return bytes(data)

    def test_roundtrip_animated_nonjoint_ancestor(self):
        data,vrs,vrm=self.pack(); p=vrview.decode_vra(data,vrs=vrs,vrm=vrm)
        self.assertEqual(p['bones'],[('tip',1),('root',-1)])
        self.assertEqual(vrview.sample(p,'release',.5)['bones'][1][:3],(3.,0.,0.))
        self.assertEqual(vrview.sample(p,'release',.5)['actors'][0][:3],(3.,0.,2.))
        self.assertAlmostEqual(vrview.sample(p,'release',.5)['actors'][0][5],math.sqrt(.5),places=6)

    def test_clamp_loop_step_and_endpoint(self):
        data,*_=self.pack(loop=True); p=vrview.decode_vra(data)
        self.assertEqual(vrview.sample(p,'release',1)['visible'],[1])
        self.assertEqual(vrview.sample(p,'release',1,clamp=True)['visible'],[0])
        self.assertEqual(vrview.sample(p,'release',.999)['visible'],[1])
        self.assertEqual(vrview.sample(p,'release',-.5)['bones'][1][:3],(3.,0.,0.))

    def test_single_frame_neutral_holds(self):
        scene=self.scene(); vrs,vrm,actors=scene.companions(['gun']); bones,g=scene.sample(0)
        clip={'name':'neutral','loop':True,'frames':[{'time':0.,'bones':bones,'actors':[vrview.decompose(g[5])],'visible':[1]}]}
        p=vrview.decode_vra(vrview.encode_vra(scene.skin.bones,actors,[clip],vrs,vrm))
        self.assertEqual(vrview.sample(p,'neutral',999)['time'],0)

    def test_source_skin_preserves_eight_weights(self):
        attrs=self.doc['meshes'][0]['primitives'][0]['attributes']
        attrs['JOINTS_1']=attrs['JOINTS_0']; attrs['WEIGHTS_1']=attrs['WEIGHTS_0']
        scene=self.scene(); vertex=scene.skin.output_meshes[0][4][0]
        self.assertEqual(vertex[8:16],(0,1,0,0,0,1,0,0))
        self.assertEqual(vertex[16:24],(.375,.125,0,0,.375,.125,0,0))
        self.assertEqual(scene.skin.bones[0][3][12:15],(-2.,-3.,-4.))

    def test_shortest_path_rotation(self):
        q=(0.,0.,math.sqrt(.5),math.sqrt(.5))
        self.assertEqual(vrview.slerp(q,tuple(-x for x in q),.5),q)

    def test_bad_animation_cases(self):
        cases=[]
        d=copy.deepcopy(self.doc);d['animations'][0]['channels'].append(copy.deepcopy(d['animations'][0]['channels'][0]));cases.append(d)
        d=copy.deepcopy(self.doc);d['animations'][0]['samplers'][0]['interpolation']='CUBICSPLINE';cases.append(d)
        d=copy.deepcopy(self.doc);d['animations'][0]['channels'][0]['target']['path']='weights';cases.append(d)
        d=copy.deepcopy(self.doc);d['animations'][0]['channels'][0]['target']['node']=999;cases.append(d)
        d=copy.deepcopy(self.doc);d['accessors'][-3]['sparse']={};cases.append(d)
        d=copy.deepcopy(self.doc);d['accessors'][-3]['count']=65537;cases.append(d)
        d=copy.deepcopy(self.doc);d['nodes'][0].pop('translation');d['nodes'][0]['matrix']=list(vrpack.IDENTITY);cases.append(d)
        for doc in cases:
            with self.subTest(doc=doc):
                with self.assertRaises(vrpack.AssetError): vrview.Scene(doc,self.blob)

    def test_reject_shear_reflection_and_bad_transform(self):
        m=list(vrpack.IDENTITY);m[1]=.2
        for mat in (m,[-x if i==0 else x for i,x in enumerate(vrpack.IDENTITY)]):
            with self.assertRaises(vrpack.AssetError): vrview.decompose(mat)
        for trs in [(0,0,0,0,0,0,0,1,1,1),(0,0,0,0,0,0,1,0,1,1),(math.inf,0,0,0,0,0,1,1,1,1)]:
            with self.assertRaises(vrpack.AssetError): vrview.validate_transform(trs)

    def test_malformed_binary(self):
        data,vrs,vrm=self.pack()
        for value in (data[:-1],data+b'\0',b'x'+data[1:],self.patch(data,8,'I',2),self.patch(data,20,'I',1),self.patch(data,32,'I',129)):
            with self.assertRaises(vrpack.AssetError): vrview.decode_vra(value)
        damaged=bytearray(data);damaged[-1]=7;struct.pack_into('<I',damaged,16,zlib.crc32(damaged[24:]))
        with self.assertRaisesRegex(vrpack.AssetError,'visibility'):vrview.decode_vra(damaged)
        with self.assertRaises(vrpack.AssetError):vrview.decode_vra(data,vrs=vrs[:-1])
        with self.assertRaises(vrpack.AssetError):vrview.decode_vra(data,vrm=vrm[:-1])

    def test_binary_rejects_times_trs_names_and_budget(self):
        data,_,_=self.pack(); cursor=36; parent_offsets=[]
        for _ in range(2):
            size=struct.unpack_from('<H',data,cursor)[0];cursor+=2+size
            parent_offsets.append(cursor);cursor+=4
        cursor+=4 # actor count
        size=struct.unpack_from('<H',data,cursor)[0];cursor+=2+size
        count=struct.unpack_from('<I',data,cursor)[0];cursor+=4+4*count+64
        cursor+=4 # clip count
        size=struct.unpack_from('<H',data,cursor)[0];cursor+=2+size
        flags=cursor;start=cursor+8;stride=4+3*40+1
        corruptions=[self.patch(data,flags,'I',2),self.patch(data,flags+4,'I',65537),
                     self.patch(data,start,'f',1),self.patch(data,start+stride,'f',0),
                     self.patch(data,start,'f',float('nan')),self.patch(data,start+4,'f',10001),
                     self.patch(data,start+4+12,'4f',0,0,0,0),self.patch(data,start+4+28,'f',0),
                     self.patch(data,parent_offsets[1],'i',0),self.patch(data,38,'B',255)]
        for damaged in corruptions:
            with self.assertRaises(vrpack.AssetError):vrview.decode_vra(damaged)
        previous=vrview.MAX_TRANSFORMS
        try:
            vrview.MAX_TRANSFORMS=2
            with self.assertRaisesRegex(vrpack.AssetError,'budget'):vrview.decode_vra(data)
        finally:vrview.MAX_TRANSFORMS=previous

    def test_duplicate_actor_and_missing_assignment(self):
        for names in (['gun','gun'],[]):
            with self.assertRaises(vrpack.AssetError): self.scene().companions(names)

    def test_compile_manifest_roundtrip_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'clip.glb').write_bytes(glb(self.doc,self.blob))
            rest=copy.deepcopy(self.doc);rest.pop('animations');(root/'rest.glb').write_bytes(glb(rest,self.blob))
            manifest={'schema':vrview.SCHEMA,'actors':['gun'],'rest_glb':'rest.glb','clips':[{'name':'release','loop':False,'path':'clip.glb','times':[0,.5,1],'visibility':[[1],[1],[0]]}]}
            path=root/'export.json';path.write_text(json.dumps(manifest))
            vrs,vrm,vra=vrview.compile_manifest(path,root/'demo')
            self.assertEqual((root/'demo.vra').read_bytes(),vra)
            self.assertEqual(len(vrview.decode_vra(vra,vrs=vrs,vrm=vrm)['clips'][0]['frames']),3)
            with self.assertRaisesRegex(vrpack.AssetError,'output already'): vrview.compile_manifest(path,root/'demo')
            manifest['clips'][0]['times']=[0,.5,.5];path.write_text(json.dumps(manifest))
            with self.assertRaises(vrpack.AssetError): vrview.compile_manifest(path)

    def test_reject_nonmonotonic_and_nonfinite_accessor(self):
        acc=self.doc['accessors'][-3];view=self.doc['bufferViews'][acc['bufferView']];off=view['byteOffset']
        for first,last in [(0,0),(1,0),(0,float('nan'))]:
            blob=bytearray(self.blob);struct.pack_into('<2f',blob,off,first,last)
            with self.assertRaises(vrpack.AssetError):vrview.Scene(self.doc,blob)

    def test_material_compatibility_is_explicit(self):
        self.doc['materials']=[{'name':'Original two sided','doubleSided':True}]
        with self.assertRaises(vrpack.AssetError): self.scene()
        with self.assertRaises(vrpack.AssetError): vrview.Scene(self.doc,self.blob,base_color_only=True)
        scene=vrview.Scene(self.doc,self.blob,single_sided_materials=True)
        self.assertIn('Original two sided',scene.warnings[0])
        self.assertTrue(self.doc['materials'][0]['doubleSided'])

    def test_rigid_extra_skin_only_one_positive_joint(self):
        self.doc['nodes'][0]['name']='Arms';self.doc['skins'][0]['name']='Arms'
        self.doc['nodes'] += [{'name':'Weapon','children':[7]}, {'name':'weapon_joint','children':[8]}, {'name':'unused_control'}]
        self.doc['scenes'][0]['nodes'].append(6)
        self.doc['skins'].append({'name':'Weapon','joints':[7,8]})
        self.doc['nodes'][5]['skin']=1
        attrs=self.doc['meshes'][0]['primitives'][0]['attributes']
        rigid_attrs=self.doc['meshes'][1]['primitives'][0]['attributes']
        rigid_attrs.update({k:v for k,v in attrs.items() if k.startswith(('JOINTS','WEIGHTS'))})
        with self.assertRaisesRegex(vrpack.AssetError,'extra skin'):
            vrview.Scene(self.doc,self.blob,armature='Arms')
        with self.assertRaisesRegex(vrpack.AssetError,'one positively weighted'):
            vrview.Scene(self.doc,self.blob,armature='Arms',rigid_armatures=['Weapon'])
        weights=self.doc['accessors'][attrs['WEIGHTS_0']];view=self.doc['bufferViews'][weights['bufferView']]
        blob=bytearray(self.blob)
        for i in range(3):struct.pack_into('<4f',blob,view['byteOffset']+i*16,1,0,0,0)
        scene=vrview.Scene(self.doc,blob,armature='Arms',rigid_armatures=['Weapon'])
        self.assertEqual(scene.actor_node(5),7)
        vrs,vrm,actors=scene.companions(['gun'])
        self.assertEqual(actors[0]['meshes'],[0])
        self.assertEqual(vrpack.inspect_vrm(vrm)['vertices'],3)
        struct.pack_into('<4f',blob,view['byteOffset'],.5,0,0,0)
        with self.assertRaisesRegex(vrpack.AssetError,'sum to one'):
            vrview.Scene(self.doc,blob,armature='Arms',rigid_armatures=['Weapon'])

    @unittest.skipUnless(os.environ.get('VRVIEW_BLENDER_TESTS')=='1' and shutil.which('blender'),
                         'set VRVIEW_BLENDER_TESTS=1 to run original Blender neutral smoke')
    def test_blender_no_action_neutral_and_source_unchanged(self):
        tools=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); env=dict(os.environ,BLENDER_USER_CONFIG=str(root/'config'))
            subprocess.run(['blender','-b','--factory-startup','--python-exit-code','1','--python',str(tools/'make_viewmodel_fixture.py'),'--','--out',str(root)],check=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            script=root/'check.py'
            script.write_text("""
import bpy,sys,json
from pathlib import Path
from mathutils import Matrix
sys.path.insert(0,TOOLS)
import export_viewmodel,vrview
root=Path(ROOT)
bpy.context.scene.frame_set(1)
B=Matrix(((1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))
rig=bpy.data.objects['Fixture Master']
expected={b.name: B@rig.matrix_world@b.matrix for b in rig.pose.bones}
for action in list(bpy.data.actions):bpy.data.actions.remove(action,do_unlink=True)
assert len(bpy.data.actions)==0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'no-action.blend'))
r=json.loads((root/'fixture-registry.json').read_text());r['clips']=[r['clips'][0]]
(root/'neutral.json').write_text(json.dumps(r))
result=export_viewmodel.export(root/'neutral.json',root/'export','neutral')
assert result['source_unchanged'] and len(bpy.data.actions)==0
pack=vrview.decode_vra((root/'export/neutral.vra').read_bytes())
pose=vrview.sample(pack,'neutral',0);globals={}
def g(i):
 if i not in globals:
  m=vrview.matrix(pose['bones'][i]);parent=pack['bones'][i][1]
  globals[i]=vrview.matmul(g(parent),m) if parent!=-1 else m
 return globals[i]
error=max(abs(g(i)[r*4+c]-expected[name][r][c]) for i,(name,parent) in enumerate(pack['bones']) for r in range(4) for c in range(4))
assert error<2e-5,error
(root/'PASS').write_text(str(error))
""".replace('TOOLS',repr(str(tools))).replace('ROOT',repr(str(root))))
            process=subprocess.run(['blender','-b',str(root/'fixture.blend'),'--python-exit-code','1','--python',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            self.assertEqual(process.returncode,0,process.stdout)
            self.assertTrue((root/'PASS').exists(),process.stdout)

    def test_matrix_decomposition_roundtrip(self):
        q=vrpack.normalized((.2,.3,.4,.8),'q');trs=(1.,2.,3.)+q+(2.,3.,4.)
        reconstructed=vrview.matrix(vrview.decompose(vrview.matrix(trs)))
        self.assertLess(max(abs(a-b) for a,b in zip(reconstructed,vrview.matrix(trs))),1e-12)


if __name__=='__main__':unittest.main()
