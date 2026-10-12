# ADS v9 forward: vertical-channel half-period test

Candidate ads-v9-depthphase-forward-public47-r5, by Aella. Diagnostic, unreviewed WIP. V8 remains a separate historical candidate at Fail54.

## Observed residual and single change

The visible R2 glove-cuff seam has strong downward pulses near outputframes28/78 and weaker ones near55/104. The saved v8 forearm surfaces have the opposite strong/weak pattern, with large pulses55/102 and smaller ones32/80. The beats are close but their alternation differs. The tracked source seam is not an anatomical wrist;26proxy crops were manually inspected, with100other frames retained as predictions. Different model surfaces are not used to derive an amplitude ratio.

A separate45% native-arm-articulation probe reduced visible forearm travel and increased the joint-anchor residual. It was not selected. The previously considered1.5×/1.35 vertical curve was never built and is not part of v9.

V9 makes one change: the vertical optical target samples the same native forward curve at phase+19frames, half its38frame period. Horizontal target and15% native arm articulation retain the primary phase. No amplitude gain, camera movement, geometry change, guard widening, or per-frame reference fitting is added.

## Source, phase and output

Public ADS47 source SHA2563acdf3e2d04757d719ba59ede08decdf8bad48e2e87d9448046fe8edcbba4f58. HIP r5 source is at RHS059/rust_duty commit493c202477604892ee6d332fc24ef01e8703f1ae, assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend, SHA25636d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d.

Native Action hip_walk_forward_r5 has frames1–39 at60fps,38unique frames and repeated endpoint. At output index j, primary native frame =1+(((j+5.75)*0.8) mod38); auxiliary vertical frame =1+(((j+5.75)*0.8+19) mod38). The primary clock,4/5 playback rate, prior23/240s comparison offset, and reference window2298–2423 are unchanged. This is an explicit channel-phase change, not a new global reference alignment.

The published native blend is ads_v9_depthphase_public47_hipr5_diagnostic.blend, SHA256094c54c25815126479ca30051a15b8e8dd8f0b4f7bab0767ba96599534652c62, scene ADS V9 Depth Phase Diagnostic. It is a lossless compact copy of the rendered source SHA2564de3a9001f0aed96123d566e30259119453e9beba253352a783f598bb739c8d3. Both decode to the identical102,920,700-byte native stream, SHA2567247b12f7e620a072e5964dea4486587b61122ccf2ad8aa226c53b6772064ec9. Blender reopened the compact copy and all68Actions, NLA, images, drivers, rests, meshes, cameras and10 evaluated witnesses matched exactly. See FORMAT_PROVENANCE.json; compressed file bytes differ, with no motion revision. Three editable output Actions are DIAG_v9_forward_native15_output, DIAG_v9_hk416_weapon_output, and DIAG_v9_hk416_magazine_output. They bake outputframes1–126 at60fps with quarter-frame keys; they are not seamless loop assets.

Runtime use would require primary and half-period native samples and would keep the primary clock continuous. The preview bake itself must not be looped. Other directions, diagonal mixtures, transitions, export and runtime equivalence are untested for this experimental mapping.

## Preservation and limitations

The exact saved blend was reopened. All65original Actions,14mesh/UV/weight/parent fingerprints, original rest, camera, source NLA, drivers and packed images are preserved. Only the isolated diagnostic scene/rig/output Actions are added.

Across501quarter-frame ideal samples, maximum hand-to-weapon translation change is0.0001054mm, hand rotation change is zero within measurement, and minimum raw wrist-guard margin is1.9142degrees. Anatomical joint-anchor residue remains1.3079mm versus0.3692mm in the input. These are numerical observations, not visible-contact or anatomy approval.

The inherited local-LRS bake limitation remains a failed check: maximum deform-matrix component residue4.10825e-5 exceeds the unchanged1e-5 threshold. Rigid-actor residue is3.7998e-7 and saved hand translation residue0.015495mm. The all-bone maximum0.00105393 occurs on nondeforming OUT_hand_l. Failed bake experiments were preserved separately; none silently replaces this output or changes its tolerance.

The reference panel is the exact already-published960x540 source proxy for R2frames2298–2423. Original720p source bytes remain unavailable locally. The preview uses true foreground Eevee rendered viewport capture only,8samples,960x540,60fps, with original camera and lighting. No score is assigned by the author.

## Reproduction

Set ADS_V9_HIP_SOURCE to the hash-verified HIP r5 path, open the exact public ADS47 native file in Blender4.3.2, and execute build_v9_diagnostic.py. Repository scripts resolve the public ADS path relative to their authoring directory; the HIP r5 input remains explicitly supplied and hash-checked. verify_v9_reopen.py performs data checks without rendering. capture_v9_eevee.py runs only in a foreground Blender window with the saved diagnostic loaded and capture_request.json mode smoke or full.

The26-case v9_native_runtime_oracle.json pins the two native inputs and expected optical offsets, including loop-boundary quarters. Its ideal actor offset agrees with the reopened rendered-source actor within2.81e-7 per matrix component. It is a mapping oracle, not runtime or reference-fidelity approval.
