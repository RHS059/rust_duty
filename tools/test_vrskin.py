#!/usr/bin/env python3
"""Original synthetic tests; never read or bundle licensed art."""
import copy
import io
from pathlib import Path
import struct
import sys
import unittest
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import make_skin_fixture
import vrpack
import vrskin
import verify_skin_bind


class SkinTests(unittest.TestCase):
    def setUp(self):
        self.glb, self.vrs = make_skin_fixture.build()
        self.doc, self.blob = vrpack.parse_glb(self.glb)

    def convert(self, **options):
        return vrskin.Converter(self.doc, self.blob, **options).convert()

    def append_accessor(self, fmt, rows, component, kind, normalized=False):
        blob = bytearray(self.blob[:self.doc['buffers'][0]['byteLength']])
        blob.extend(b'\0' * ((-len(blob)) % 4))
        offset = len(blob)
        for row in rows: blob.extend(struct.pack('<' + fmt, *row))
        views, accs = self.doc['bufferViews'], self.doc['accessors']
        views.append({'buffer':0, 'byteOffset':offset, 'byteLength':len(blob)-offset})
        accs.append({'bufferView':len(views)-1, 'componentType':component, 'count':len(rows), 'type':kind, 'normalized':normalized})
        self.doc['buffers'][0]['byteLength'] = len(blob)
        self.blob = bytes(blob) + b'\0' * ((-len(blob)) % 4)
        return len(accs)-1

    @property
    def attrs(self): return self.doc['meshes'][0]['primitives'][0]['attributes']

    def patch_vrs(self, offset, fmt, *values):
        b = bytearray(self.vrs)
        struct.pack_into('<' + fmt, b, offset, *values)
        struct.pack_into('<I', b, 16, zlib.crc32(b[24:]))
        return bytes(b)

    def test_exact_independently_encoded_fixture(self):
        self.assertEqual(self.convert(), self.vrs)
        info = vrskin.inspect_vrs(self.vrs)
        self.assertEqual((info['bones'],info['vertices'],info['triangles']), (2,3,1))

    def test_nonjoint_ancestors_and_forward_joint_parent(self):
        converter = vrskin.Converter(self.doc, self.blob)
        converter.convert()
        tip, root = converter.bones
        self.assertEqual(tip[1],1)
        self.assertEqual(tip[2][12:15], (0,3,4))
        self.assertEqual(root[2][12:15], (2,0,0))
        # Transformed mesh node is ignored by correct world-space skinning.
        self.assertEqual(converter.output_meshes[0][4][1][:3], (1,0,0))

    def test_full_independent_bind_pose_verifier(self):
        report = verify_skin_bind.verify(self.glb, self.convert())
        self.assertTrue(report['passed'])
        self.assertEqual(report['max_skinned_position_component_error'], 0)

    def test_embedded_rgba_texture_preserved(self):
        from PIL import Image
        image = Image.new('RGBA', (2, 2), (11, 22, 33, 255))
        encoded = io.BytesIO(); image.save(encoded, format='PNG')
        png = encoded.getvalue()
        blob = bytearray(self.blob[:self.doc['buffers'][0]['byteLength']])
        blob.extend(b'\0' * ((-len(blob)) % 4)); start = len(blob); blob.extend(png)
        self.doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':len(png)})
        self.doc['images'] = [{'bufferView':len(self.doc['bufferViews'])-1,'mimeType':'image/png'}]
        self.doc['textures'] = [{'source':0}]
        self.doc['materials'] = [{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}]
        self.doc['meshes'][0]['primitives'][0]['material']=0
        self.doc['buffers'][0]['byteLength']=len(blob)
        self.blob=bytes(blob)+b'\0'*((-len(blob))%4)
        converter=vrskin.Converter(self.doc,self.blob)
        out=converter.convert(); info=vrskin.inspect_vrs(out)
        self.assertEqual(info['texture_bytes'],16)
        self.assertEqual(converter.output_meshes[0][3],bytes([11,22,33,255])*4)

    def test_v1_still_strictly_rejects_skins(self):
        with self.assertRaises(vrpack.AssetError): vrpack.Converter(self.doc,self.blob)

    def test_eight_influences_preserved(self):
        self.attrs['JOINTS_1'] = self.append_accessor('4B',[(1,0,1,0)]*3,5121,'VEC4')
        self.attrs['WEIGHTS_1'] = self.append_accessor('4f',[(.1,.2,.3,.4)]*3,5126,'VEC4')
        out = self.convert()
        vertex = struct.unpack_from('<8f8H8f',out,351)
        self.assertEqual(vertex[8:16],(0,1,0,0,1,0,1,0))
        for actual,wanted in zip(vertex[16:24], [.375,.125,0,0,.05,.1,.15,.2]):
            self.assertAlmostEqual(actual,wanted,places=6)

    def test_normalized_integer_weights(self):
        self.attrs['WEIGHTS_0'] = self.append_accessor('4B',[(192,63,0,0)]*3,5121,'VEC4',True)
        out = self.convert()
        weights = struct.unpack_from('<8f',out,351+48)
        self.assertAlmostEqual(weights[0],192/255,places=6)

    def test_absent_inverse_binds_default_to_identity(self):
        del self.doc['skins'][0]['inverseBindMatrices']
        converter = vrskin.Converter(self.doc,self.blob); converter.convert()
        self.assertEqual(converter.bones[0][3],vrpack.IDENTITY)

    def test_material_omissions_need_flag_and_announce(self):
        self.doc['materials'] = [{'normalTexture':{'index':0}, 'occlusionTexture':{'index':0}, 'pbrMetallicRoughness':{'metallicRoughnessTexture':{'index':0}}}]
        with self.assertRaisesRegex(vrpack.AssetError,'base-color-only'): self.convert()
        converter = vrskin.Converter(self.doc,self.blob,base_color_only=True)
        converter.convert()
        self.assertIn('normalTexture',converter.warnings[0]); self.assertIn('occlusionTexture',converter.warnings[0])
        self.assertIn('metallicRoughnessTexture',converter.warnings[0])

    def test_mipmap_omission_needs_flag(self):
        self.doc['samplers']=[{'minFilter':9987}]
        with self.assertRaisesRegex(vrpack.AssetError,'base-color-only'): self.convert()
        c = vrskin.Converter(self.doc,self.blob,base_color_only=True); c.convert()
        self.assertIn('mipmap',c.warnings[0])

    def test_rejects_multiple_skins_and_missing_skin(self):
        for skins in [[], self.doc['skins']*2]:
            d=copy.deepcopy(self.doc); d['skins']=skins
            with self.assertRaises(vrpack.AssetError): vrskin.Converter(d,self.blob)
        del self.doc['nodes'][4]['skin']
        with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_bad_hierarchy(self):
        for idx, children in [(3,[0]),(0,[1,1,4])]:
            d=copy.deepcopy(self.doc); d['nodes'][idx]['children']=children
            with self.assertRaises(vrpack.AssetError): vrskin.Converter(d,self.blob).convert()

    def test_rejects_missing_or_duplicate_joint(self):
        for joints in [[3,3],[3,5],[],[True,1]]:
            self.doc['skins'][0]['joints']=joints
            with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_invalid_source_weights(self):
        for row in [(0,0,0,0),(-.1,1,0,0),(float('nan'),1,0,0),(2,0,0,0)]:
            self.attrs['WEIGHTS_0']=self.append_accessor('4f',[row]*3,5126,'VEC4')
            with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_bad_skin_accessors(self):
        for field,value in [('normalized',True),('componentType',5126),('count',4),('sparse',{})]:
            d=copy.deepcopy(self.doc); d['accessors'][self.attrs['JOINTS_0']][field]=value
            with self.assertRaises(vrpack.AssetError): vrskin.Converter(d,self.blob).convert()
        self.attrs['JOINTS_1']=self.attrs['JOINTS_0']
        with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_out_of_range_joint_even_at_zero_weight(self):
        self.attrs['JOINTS_0']=self.append_accessor('4H',[(0,1,2,0)]*3,5123,'VEC4')
        with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_extensions_animations_morphs(self):
        for field,value in [('animations',[{}]),('extensionsUsed',['something'])]:
            d=copy.deepcopy(self.doc); d[field]=value
            with self.assertRaises(vrpack.AssetError): vrskin.Converter(d,self.blob)
        self.doc['meshes'][0]['primitives'][0]['targets']=[]
        with self.assertRaises(vrpack.AssetError): self.convert()

    def test_rejects_every_truncation_and_bad_header(self):
        for n in range(len(self.vrs)):
            with self.assertRaises(vrpack.AssetError): vrskin.inspect_vrs(self.vrs[:n])
        for offset in [0,8,12,16,20]:
            b=bytearray(self.vrs); b[offset]^=1
            with self.assertRaises(vrpack.AssetError): vrskin.inspect_vrs(b)

    def test_rejects_malformed_records(self):
        patches=[(24,'I',129),(28,'H',65),(30,'B',255),(33,'i',0),(171,'i',0),
                 (37,'f',float('nan')),(49,'f',1.),(37,'f',0.),(303,'I',129),
                 (307,'f',2.),(331,'I',2049),(339,'I',4),(343,'I',1000001),
                 (347,'I',4),(351,'f',10001.),(371,'f',0.),(375,'f',1000001.),
                 (383,'H',2),(397,'H',2),(399,'f',0.),(427,'f',.1),(591,'I',3)]
        for offset,fmt,value in patches:
            with self.subTest(offset=offset):
                with self.assertRaises(vrpack.AssetError): vrskin.inspect_vrs(self.patch_vrs(offset,fmt,value))

    def test_rejects_trailing_payload(self):
        b=bytearray(self.vrs)+b'\0';struct.pack_into('<I',b,12,len(b)-24);struct.pack_into('<I',b,16,zlib.crc32(b[24:]))
        with self.assertRaises(vrpack.AssetError): vrskin.inspect_vrs(b)


if __name__=='__main__': unittest.main()
