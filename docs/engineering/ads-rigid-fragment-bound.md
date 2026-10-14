# Bounded rigid fragment/output audit

Status: implementation facts and a numerical checker are established; the
complete native three-byte fragment bound is not yet established. No acceptance
flag, calibration, contrast threshold, source mask, or captured image is changed.

## Exact scope

The existing source certificate uses a per-channel error allowance of three
byte values, background RGB `(36,48,61)`, and contrast tolerance eight. Original
companion inspection reduces every required sample to an untextured rigid mesh:
its fallback is immutable white RGBA `(255,255,255,255)`. Skin texture envelopes
cannot satisfy the certificate's contrast predicate; their possible support is
subtracted from required support. Thus this audit does not need a bound for
arbitrary skin texture filtering. Source vertex colors and actor opacity still
need exact input/execution binding.

## Retrieved implementation identity

The official Mesa archive is `https://archive.mesa3d.org/mesa-26.2.4.tar.xz`.
Its SHA256 is
`bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9`, matching
the [official release checksum](https://docs.mesa3d.org/relnotes/26.2.4.html).
The local `../evidence/ads-source-visibility/mesa-26.2.4-fragment-source.json` pins the individual reviewed files.

## Facts established by that source

1. `src/mesa/state_tracker/st_format.c:1206` chooses a matching unsigned UNORM
   format for unsized formats. The `GL_RGBA` format table at line 264 selects
   `PIPE_FORMAT_R8G8B8A8_UNORM`; the llvmpipe format support path is in
   `lp_screen.c:640`. This resolves the unsized `GL_RGBA/GL_UNSIGNED_BYTE`
   target's storage choice for this pinned implementation. It is not a claim
   that OpenGL universally mandates RGBA8 for an unsized request.
2. `lp_bld_interp.c:810` explicitly uses 32-bit floating setup and interpolation
   values. `lp_state_setup.c:374` constructs attribute planes. Fragment plane
   evaluation is at `lp_bld_interp.c:132`; perspective correction uses a
   reciprocal followed by multiplication at line 472. `lp_bld_arit.c:2447`
   implements the reciprocal using LLVM floating division and explicitly
   disables its approximate-RCP branch.
3. This does not make all shader operations binary32. For ES shaders,
   `glsl_parser_extras.cpp:2488` invokes precision lowering when fp16 is
   supported. `lower_precision.cpp:724` inserts/propagates half conversions.
   The reported lowp/mediump ten-bit precision agrees with
   `st_extensions.c:318`. GLSL ES 1.00 itself leaves operation precision
   implementation dependent ([section 5.12](https://www.khronos.org/files/opengles_shading_language.pdf)).
4. `lp_state_fs.c:1811` derives an eight-bit normalized blending representation
   from RGBA8 and at line 2791 converts fragment output to it before blending.
   `lp_bld_conv.c:266` performs the float-to-UNORM conversion; for eight bits
   its scale/bias path rounds to the nearest byte, with binary32 arithmetic
   error far below one byte. The checker conservatively reserves `0.5001`
   byte for this conversion, after clamping to `[0,1]`.
   `st_atom_blend.c:336` passes the GL dither state, since
   `u_screen.c:50` initializes its capability to true. The pinned llvmpipe
   color conversion/blend path does not use that flag; its only implemented
   dither is alpha-to-coverage, which is inactive for this single-sample target.
   Thus the native color path must not be described as having a queried or
   default-disabled GL dither state.
5. At alpha byte 255, source-over factors become 255 and zero. The integer
   multiplication in `lp_bld_arit.c:796` preserves both endpoints exactly.
   Exhaustive checking of all 65,536 input products reproduces the exact
   nearest-integer value of `a*b/255`. This verifies the endpoint algebra;
   the alpha-one source supplies a further algebraic reduction: clipping uses
   `OUT+t*(IN-OUT)`, so equal alpha-one endpoints remain one. Premultiplication
   by reciprocal-w therefore gives exactly the same plane inputs as position
   reciprocal-w. Setup/evaluation produces the same `q` for both; `q*(1/q)`
   differs from one by at most two full binary32 ulps when finite and normal.
   Even a conservative following half conversion rounded toward zero keeps
   alpha above `254.5/255`, so UNORM8 conversion rounds it to 255. The test
   verifies that margin and both half/single constant-reciprocal variants of
   `255/255`. This needs the finite positive `q` premise checked from geometry;
   a nominal source opacity of one by itself is insufficient.
6. The game's GL capture function only reverses row order and, for display
   captures, replaces alpha with 255. The DX12 path strips padding and copies
   texture bytes. Neither changes RGB or applies display gamma during PNG
   encoding. The captured viewmodel target is the relevant path, rather than
   a later window-system presentation conversion.

## Why finite geometry matters

`lp_state_setup.c:359` explicitly documents potentially large errors for small
triangles far from the framebuffer origin, due to cancellation in its plane
representation. A precision capability receipt alone cannot resolve this.

`ads_fragment_error_bound.py` implements conservative forward-error propagation of
the actual setup/evaluation structure, with one full binary32 ulp relative error
per operation, outward host bounds, a subnormal/flush allowance, and all six
vertex permutations. Separate multiply/add bounds include tighter fused
operations. Nonfinite values, degenerate area intervals, and divisors that could
cross zero are rejected. It accounts for distinct reciprocal and multiplication
operations. It never emits acceptance/profile approval flags.

The function's contract requires independently bounded, actual post-clip
positions, reciprocal-w and color values. Its convexity tightening applies only
where covered sample interpolation is independently known to remain convex,
or after adding its explicit snapping allowance. LlvmPipe uses unsnapped
positions for interpolator setup but snapped positions for coverage. A covered
point of the snapped triangle is at most the declared per-axis displacement
from a convex point of the unsnapped triangle. The exact numerator and
reciprocal-w plane gradients bound this extrapolation separately from roundoff;
the denominator must stay positive after both allowances. A triangle whose own
interior is robust is insufficient by itself:
every possible depth winner at a required sample must be safe. X/Y-clipped
triangles also require clipping-induced color/position errors to be included.
The shader normalization envelope enters each original vertex color before
clipping, so signed interpolation weights cannot silently amplify an error
that was added only afterward.

`narrow_ads_fragment_support.py` applies the unchanged three-byte allowance to this
finite input. Any unresolved or excessive bound makes that subtriangle unsafe.
It removes the subtriangle's entire possible overlap from required support,
even if another triangle supplies a robust interior at the same sample. This
only narrows a source obligation. It neither enlarges the allowed error nor
reads capture pixels to choose its geometry. Every output keeps native-profile
verification false and the acceptance verdict null.

## Remaining finite closure

The bounded source replay and conservative clipping supplement have now been
evaluated for all 50 visible fallback frames. The reviewed clipping packet has
SHA256 `458655709d010fd004eccc04234094ec09d66428e286e47c892ab5578d9a3204`.
It includes lowp color normalization before clipping, alternative uncertain
clip outcomes, and both snapped and unsnapped positions. Its local replay masks
and gameplay state match the retained native source JSONL; matching those
outputs still does not observe the native GPU's internal vertex values.

Of 53,473 overlapping subtriangles, 1,487 have uncertified or excessive bounds
and their complete possible overlap is removed. Required support narrows from
49,716 to 47,558 samples. Every frame retains positive support, with a minimum
of four samples at frames 258 and 467. The largest retained subtriangle bound
is 2.999029107661553 bytes per channel. The existing three-byte allowance,
clear color and eight-byte contrast tolerance are unchanged. The public
bounded summary records counts and hashes without source geometry or assets.

Remaining work is native implementation/input/execution binding and independent
acceptance integration. The source replay runs on the current host and is not an
observation of the original Windows execution. These results must not promote
the original diagnostic flags, authorize arbitrary triangles, substitute for
the strict native image checks, or imply the full migration aggregate passed.

The D3D shader path uses Rgba8Unorm and f32 shader values. Microsoft's
[Direct3D functional specification](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm)
requires floating-point rules for attribute interpolation (15.16.2), but does
not identify a WARP interpolation operation graph. Mesa's specific graph must
not be substituted as a proof for WARP. The minimal residual native
corroboration, if needed, should target the unresolved finite triangles and
output properties using the exact adapter/runtime, rather than rerender the
whole scenario suite or change calibration.

## Checks

Run `python -m unittest -v test_ads_fragment_error_bound.py test_narrow_ads_fragment_support.py` from `tools/`.
Ten tests pass across the numerical helper and narrowing caller: exhaustive
UNORM multiplication/endpoints, opaque alpha margin, independently sampled
binary32 operation containment, nonfinite/overflow/degenerate rejection,
well-conditioned and skinny-triangle cases, explicit snapping extrapolation,
strict run validation, complete unsafe-winner subtraction, and fail-closed
unresolved intervals.
