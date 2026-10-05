//! GPU world lighting: cascaded sun shadows, sky, physically based lit pass with
//! SSAO and exponential height fog, ACES tonemap and bloom. Structure follows
//! Unreal's default outdoor pipeline; the light model is `vector_range::lighting`.
//!
//! GL2/GLES2-safe: no float or depth-texture sampling. Shadow and scene depth
//! are packed into RGBA8; the lit pass tonemaps directly and stores a bloom
//! weight (how far the pre-tonemap pixel exceeds the threshold) in alpha.
use macroquad::miniquad::{
    BlendState, Comparison, PipelineParams, ShaderSource, UniformDesc, UniformType,
};
use macroquad::prelude::*;
use macroquad::texture::RenderPass;
use vector_range::lighting::{cascade_splits, fit_cascade, LightEnvironment, LightingTuning};

pub const CASCADES: usize = 3;
const SHADOW_DEPTH_RANGE: f32 = 100.;

/// The world camera for one frame.
pub struct FrameView {
    pub eye: Vec3,
    pub forward: Vec3,
    pub up: Vec3,
    pub fovy: f32,
    pub aspect: f32,
    pub near: f32,
    pub far: f32,
}
impl FrameView {
    fn camera(&self, target: &RenderTarget) -> Camera3D {
        Camera3D {
            position: self.eye,
            target: self.eye + self.forward,
            up: self.up,
            fovy: self.fovy,
            aspect: Some(self.aspect),
            z_near: self.near,
            z_far: self.far,
            render_target: Some(target.clone()),
            ..Default::default()
        }
    }
    fn view_projection(&self) -> Mat4 {
        Mat4::perspective_rh_gl(self.fovy, self.aspect, self.near, self.far)
            * Mat4::look_at_rh(self.eye, self.eye + self.forward, self.up)
    }
}

/// An exact view-projection rendering into a target (shadow cascades).
struct MatrixCamera {
    matrix: Mat4,
    pass: RenderPass,
}
impl Camera for MatrixCamera {
    fn matrix(&self) -> Mat4 {
        self.matrix
    }
    fn depth_enabled(&self) -> bool {
        true
    }
    fn render_pass(&self) -> Option<RenderPass> {
        Some(self.pass.clone())
    }
    fn viewport(&self) -> Option<(i32, i32, i32, i32)> {
        None
    }
}

/// Fullscreen pass: a unit rectangle covers the target; shaders use gl_FragCoord.
struct ScreenPass {
    pass: Option<RenderPass>,
}
impl Camera for ScreenPass {
    fn matrix(&self) -> Mat4 {
        Mat4::orthographic_rh_gl(0., 1., 0., 1., -1., 1.)
    }
    fn depth_enabled(&self) -> bool {
        false
    }
    fn render_pass(&self) -> Option<RenderPass> {
        self.pass.clone()
    }
    fn viewport(&self) -> Option<(i32, i32, i32, i32)> {
        None
    }
}

const COMMON: &str = r#"
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
vec4 pack(float v) {
    vec4 enc = fract(vec4(1.0, 255.0, 65025.0, 16581375.0) * v);
    return enc - enc.yzww * vec4(1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0, 0.0);
}
float unpack(vec4 c) {
    return dot(c, vec4(1.0, 1.0 / 255.0, 1.0 / 65025.0, 1.0 / 16581375.0));
}
vec3 aces(vec3 x) {
    x = max(x, 0.0);
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
vec4 display(vec3 radiance, float exposure, float threshold) {
    vec3 exposed = radiance * exposure;
    float peak = max(exposed.r, max(exposed.g, exposed.b));
    float bloom = clamp((peak - threshold) / max(threshold, 0.001), 0.0, 1.0);
    return vec4(pow(aces(exposed), vec3(1.0 / 2.2)), bloom);
}
"#;

const MESH_VERTEX: &str = r#"#version 100
attribute vec3 position;
attribute vec2 texcoord;
attribute vec4 color0;
attribute vec4 normal;
varying vec2 uv;
varying vec4 color;
varying vec3 wpos;
varying vec3 wnormal;
uniform mat4 Model;
uniform mat4 Projection;
void main() {
    vec4 w = Model * vec4(position, 1.0);
    wpos = w.xyz;
    wnormal = (Model * vec4(normal.xyz, 0.0)).xyz;
    color = color0 / 255.0;
    uv = texcoord;
    gl_Position = Projection * w;
}"#;

const FULLSCREEN_VERTEX: &str = r#"#version 100
attribute vec3 position;
attribute vec2 texcoord;
attribute vec4 color0;
uniform mat4 Model;
uniform mat4 Projection;
void main() {
    gl_Position = Projection * Model * vec4(position, 1.0);
}"#;

const DEPTH_FRAGMENT: &str = r#"
uniform float Mode;
uniform float Far;
void main() {
    // Mode 0: light-space window depth. Mode 1: linear view depth / Far.
    float v = Mode < 0.5 ? gl_FragCoord.z : (1.0 / gl_FragCoord.w) / Far;
    gl_FragColor = pack(clamp(v, 0.0, 0.99999));
}"#;

const LIT_FRAGMENT: &str = r#"
varying vec2 uv;
varying vec4 color;
varying vec3 wpos;
varying vec3 wnormal;
uniform sampler2D Texture;
uniform sampler2D Shadow0;
uniform sampler2D Shadow1;
uniform sampler2D Shadow2;
uniform sampler2D AoTex;
uniform mat4 ShadowMat0;
uniform mat4 ShadowMat1;
uniform mat4 ShadowMat2;
uniform vec3 CascadeEnds;
uniform vec3 CascadeTexel;
uniform float ShadowSoftness;
uniform float ShadowMapTexel;
uniform float DepthScale;
uniform vec3 SunDir;
uniform vec3 SunColor;
uniform vec3 SkyColor;
uniform vec3 GroundColor;
uniform vec3 HorizonColor;
uniform vec3 CameraPos;
uniform vec3 CameraForward;
uniform float Exposure;
uniform float Roughness;
uniform vec4 Fog;
uniform vec2 ScreenSize;
uniform float AoStrength;
uniform float BloomThreshold;

float pcf(sampler2D map, vec4 clip, float texel, float bias) {
    vec3 p = clip.xyz / clip.w * 0.5 + 0.5;
    if (p.x <= 0.0 || p.x >= 1.0 || p.y <= 0.0 || p.y >= 1.0 || p.z >= 1.0) return 1.0;
    float lit = 0.0;
    for (int x = -1; x <= 1; x++) {
        for (int y = -1; y <= 1; y++) {
            vec2 o = vec2(float(x), float(y)) * texel * ShadowSoftness;
            lit += (p.z - bias <= unpack(texture2D(map, p.xy + o))) ? 1.0 : 0.0;
        }
    }
    return lit / 9.0;
}

float cascade(sampler2D map, mat4 m, vec3 p, vec3 n, float texelWorld, float slope) {
    // Normal offset of ~2 texels plus a slope-scaled depth bias in world texels,
    // converted to light-depth units.
    vec3 q = p + n * texelWorld * 2.0;
    float bias = texelWorld * (1.0 + 2.0 * min(slope, 8.0)) * DepthScale;
    return pcf(map, m * vec4(q, 1.0), ShadowMapTexel, bias);
}

float shadowAt(vec3 p, vec3 n, float depth, float ndl) {
    float slope = sqrt(max(1.0 - ndl * ndl, 0.0)) / max(ndl, 0.05);
    if (depth < CascadeEnds.x) return cascade(Shadow0, ShadowMat0, p, n, CascadeTexel.x, slope);
    if (depth < CascadeEnds.y) return cascade(Shadow1, ShadowMat1, p, n, CascadeTexel.y, slope);
    if (depth < CascadeEnds.z) {
        float s = cascade(Shadow2, ShadowMat2, p, n, CascadeTexel.z, slope);
        return mix(1.0, s, clamp((CascadeEnds.z - depth) / (CascadeEnds.z * 0.1), 0.0, 1.0));
    }
    return 1.0;
}

void main() {
    vec3 albedo = pow(color.rgb * texture2D(Texture, uv).rgb, vec3(2.2));
    vec3 n = wnormal;
    n = dot(n, n) < 0.01 ? vec3(0.0, 1.0, 0.0) : normalize(n);
    vec3 toEye = CameraPos - wpos;
    float dist = length(toEye);
    vec3 v = toEye / max(dist, 0.0001);
    float ndl = max(dot(n, SunDir), 0.0);
    float depth = dot(wpos - CameraPos, CameraForward);
    float shadow = ndl > 0.0 ? shadowAt(wpos, n, depth, ndl) : 0.0;
    float ao = mix(1.0, texture2D(AoTex, gl_FragCoord.xy / ScreenSize).r, AoStrength);

    // UE default lit: Lambert + GGX (Smith-Schlick, Schlick Fresnel, F0 0.04).
    vec3 h = normalize(v + SunDir);
    float a = max(Roughness * Roughness, 0.001);
    float a2 = a * a;
    float ndh = max(dot(n, h), 0.0);
    float ndv = max(dot(n, v), 0.0001);
    float dd = ndh * ndh * (a2 - 1.0) + 1.0;
    float D = a2 / (3.14159265 * dd * dd);
    float k = a * 0.5;
    float vis = 0.25 / ((ndv * (1.0 - k) + k) * (max(ndl, 0.0001) * (1.0 - k) + k));
    float F = 0.04 + 0.96 * pow(1.0 - max(dot(v, h), 0.0), 5.0);
    vec3 sky = mix(GroundColor, SkyColor, n.y * 0.5 + 0.5);
    vec3 radiance = (albedo + vec3(D * vis * F)) * SunColor * ndl * shadow + albedo * sky * ao;

    // Exponential height fog with directional inscattering.
    float falloff = Fog.y;
    float dy = wpos.y - CameraPos.y;
    float atCamera = Fog.x * exp(-falloff * (CameraPos.y - Fog.z));
    float line = abs(falloff * dy) > 0.001 ? (1.0 - exp(-falloff * dy)) / (falloff * dy) : 1.0;
    float fog = min(1.0 - exp(-atCamera * line * dist), Fog.w);
    vec3 inscatter = HorizonColor + SunColor * 0.12 * pow(max(dot(-v, SunDir), 0.0), 8.0);
    radiance = mix(radiance, inscatter, fog);
    gl_FragColor = display(radiance, Exposure, BloomThreshold);
}"#;

const SKY_FRAGMENT: &str = r#"
uniform mat4 InvViewProj;
uniform vec3 CameraPos;
uniform vec3 SunDir;
uniform vec3 SunColor;
uniform vec3 SkyColor;
uniform vec3 HorizonColor;
uniform vec3 GroundColor;
uniform vec2 ScreenSize;
uniform float Exposure;
uniform float BloomThreshold;
void main() {
    vec2 ndc = gl_FragCoord.xy / ScreenSize * 2.0 - 1.0;
    vec4 far = InvViewProj * vec4(ndc, 1.0, 1.0);
    vec3 dir = normalize(far.xyz / far.w - CameraPos);
    float up = dir.y;
    vec3 zenith = SkyColor * vec3(0.75, 0.9, 1.25);
    vec3 col = mix(HorizonColor, zenith, pow(max(up, 0.0), 0.45));
    if (up < 0.0) col = mix(HorizonColor, GroundColor + HorizonColor * 0.3, min(-up * 4.0, 1.0));
    float c = max(dot(dir, SunDir), 0.0);
    col += SunColor * (0.06 * pow(c, 6.0) + 0.25 * pow(c, 64.0));
    col += SunColor * 30.0 * smoothstep(0.99985, 0.99996, c);
    gl_FragColor = display(col, Exposure, BloomThreshold);
}"#;

const SSAO_FRAGMENT: &str = r#"
uniform sampler2D DepthTex;
uniform vec2 TargetSize;
uniform vec2 TanHalfFov;
uniform float Far;
uniform float Radius;
float depthAt(vec2 p) { return unpack(texture2D(DepthTex, p)) * Far; }
vec3 viewPos(vec2 p, float d) {
    vec2 ndc = p * 2.0 - 1.0;
    return vec3(ndc.x * TanHalfFov.x * d, ndc.y * TanHalfFov.y * d, -d);
}
void main() {
    vec2 texel = 1.0 / TargetSize;
    vec2 p = gl_FragCoord.xy * texel;
    float d = depthAt(p);
    if (d > Far * 0.98) { gl_FragColor = vec4(1.0); return; }
    vec3 P = viewPos(p, d);
    // Reconstruct the normal from the flatter neighbor on each axis.
    vec3 r = viewPos(p + vec2(texel.x, 0.0), depthAt(p + vec2(texel.x, 0.0))) - P;
    vec3 l = P - viewPos(p - vec2(texel.x, 0.0), depthAt(p - vec2(texel.x, 0.0)));
    vec3 u = viewPos(p + vec2(0.0, texel.y), depthAt(p + vec2(0.0, texel.y))) - P;
    vec3 b = P - viewPos(p - vec2(0.0, texel.y), depthAt(p - vec2(0.0, texel.y)));
    vec3 dx = abs(r.z) < abs(l.z) ? r : l;
    vec3 dy = abs(u.z) < abs(b.z) ? u : b;
    vec3 N = normalize(cross(dx, dy));
    if (N.z < 0.0) N = -N;
    vec3 T = normalize(abs(N.y) < 0.99 ? cross(N, vec3(0.0, 1.0, 0.0)) : cross(N, vec3(1.0, 0.0, 0.0)));
    vec3 B = cross(N, T);
    float rot = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) * 6.2831853;
    float occlusion = 0.0;
    for (int i = 0; i < 12; i++) {
        float t = (float(i) + 0.5) / 12.0;
        float ang = float(i) * 2.39996 + rot;
        float s = sqrt(t);
        vec3 h = vec3(cos(ang) * s, sin(ang) * s, sqrt(1.0 - t));
        vec3 S = P + (T * h.x + B * h.y + N * h.z) * Radius * mix(0.15, 1.0, t * t);
        vec2 q = vec2(S.x / (-S.z) / TanHalfFov.x, S.y / (-S.z) / TanHalfFov.y) * 0.5 + 0.5;
        float sceneDepth = depthAt(q);
        float range = smoothstep(0.0, 1.0, Radius / max(abs(d - sceneDepth), 0.0001));
        occlusion += (sceneDepth < -S.z - 0.03 ? 1.0 : 0.0) * range;
    }
    float ao = 1.0 - occlusion / 12.0;
    gl_FragColor = vec4(ao, ao, ao, 1.0);
}"#;

const BLUR_FRAGMENT: &str = r#"
uniform sampler2D Source;
uniform vec2 TargetSize;
uniform vec2 SourceTexel;
uniform vec2 Direction;
uniform float Mode;
void main() {
    vec2 p = gl_FragCoord.xy / TargetSize;
    if (Mode < 0.5) {
        // 4x4 box (AO).
        vec4 sum = vec4(0.0);
        for (int x = -2; x < 2; x++) {
            for (int y = -2; y < 2; y++) {
                sum += texture2D(Source, p + (vec2(float(x), float(y)) + 0.5) * SourceTexel);
            }
        }
        gl_FragColor = sum / 16.0;
    } else if (Mode < 1.5) {
        // Bright pass: weight the tonemapped color by the stored bloom weight.
        vec4 sum = vec4(0.0);
        for (int x = -1; x <= 1; x += 2) {
            for (int y = -1; y <= 1; y += 2) {
                vec4 c = texture2D(Source, p + vec2(float(x), float(y)) * SourceTexel);
                sum += vec4(c.rgb * c.a, 1.0);
            }
        }
        gl_FragColor = sum / 4.0;
    } else {
        // 9-tap separable Gaussian.
        vec2 step = Direction * SourceTexel;
        vec4 sum = texture2D(Source, p) * 0.2270270;
        sum += texture2D(Source, p + step * 1.3846154) * 0.3162162;
        sum += texture2D(Source, p - step * 1.3846154) * 0.3162162;
        sum += texture2D(Source, p + step * 3.2307692) * 0.0702703;
        sum += texture2D(Source, p - step * 3.2307692) * 0.0702703;
        gl_FragColor = sum;
    }
}"#;

const COMPOSITE_FRAGMENT: &str = r#"
uniform sampler2D Scene;
uniform sampler2D Bloom;
uniform vec2 TargetSize;
uniform float BloomIntensity;
void main() {
    vec2 p = gl_FragCoord.xy / TargetSize;
    vec3 c = texture2D(Scene, p).rgb + texture2D(Bloom, p).rgb * BloomIntensity;
    gl_FragColor = vec4(min(c, vec3(1.0)), 1.0);
}"#;

fn material(
    vertex: &str,
    fragment: &str,
    uniforms: &[(&str, UniformType)],
    textures: &[&str],
    depth: bool,
) -> Result<Material, String> {
    let fragment = format!("#version 100\n{COMMON}\n{fragment}");
    load_material(
        ShaderSource::Glsl {
            vertex,
            fragment: &fragment,
        },
        MaterialParams {
            pipeline_params: PipelineParams {
                depth_write: depth,
                depth_test: if depth {
                    Comparison::LessOrEqual
                } else {
                    Comparison::Always
                },
                color_blend: None::<BlendState>,
                ..Default::default()
            },
            uniforms: uniforms
                .iter()
                .map(|(name, kind)| UniformDesc::new(name, *kind))
                .collect(),
            textures: textures.iter().map(|t| t.to_string()).collect(),
        },
    )
    .map_err(|e| format!("{e:?}"))
}

fn target(width: u32, height: u32, depth: bool, filter: FilterMode) -> RenderTarget {
    let rt = render_target_ex(
        width.max(1),
        height.max(1),
        RenderTargetParams {
            depth,
            ..Default::default()
        },
    );
    rt.texture.set_filter(filter);
    rt
}

struct Targets {
    size: (u32, u32),
    scene: RenderTarget,
    depth: RenderTarget,
    ao: RenderTarget,
    ao_blur: RenderTarget,
    bloom_a: RenderTarget,
    bloom_b: RenderTarget,
}

pub struct WorldRenderer {
    lit: Material,
    depth: Material,
    sky: Material,
    ssao: Material,
    blur: Material,
    composite: Material,
    shadows: Vec<RenderTarget>,
    shadow_resolution: u32,
    targets: Option<Targets>,
    view: Option<FrameView>,
}

impl WorldRenderer {
    pub fn new(tuning: &LightingTuning) -> Result<Self, String> {
        use UniformType::*;
        let lit = material(
            MESH_VERTEX,
            LIT_FRAGMENT,
            &[
                ("ShadowMat0", Mat4),
                ("ShadowMat1", Mat4),
                ("ShadowMat2", Mat4),
                ("CascadeEnds", Float3),
                ("CascadeTexel", Float3),
                ("ShadowSoftness", Float1),
                ("ShadowMapTexel", Float1),
                ("DepthScale", Float1),
                ("SunDir", Float3),
                ("SunColor", Float3),
                ("SkyColor", Float3),
                ("GroundColor", Float3),
                ("HorizonColor", Float3),
                ("CameraPos", Float3),
                ("CameraForward", Float3),
                ("Exposure", Float1),
                ("Roughness", Float1),
                ("Fog", Float4),
                ("ScreenSize", Float2),
                ("AoStrength", Float1),
                ("BloomThreshold", Float1),
            ],
            &["Shadow0", "Shadow1", "Shadow2", "AoTex"],
            true,
        )?;
        let depth = material(
            MESH_VERTEX,
            DEPTH_FRAGMENT,
            &[("Mode", Float1), ("Far", Float1)],
            &[],
            true,
        )?;
        let sky = material(
            FULLSCREEN_VERTEX,
            SKY_FRAGMENT,
            &[
                ("InvViewProj", Mat4),
                ("CameraPos", Float3),
                ("SunDir", Float3),
                ("SunColor", Float3),
                ("SkyColor", Float3),
                ("HorizonColor", Float3),
                ("GroundColor", Float3),
                ("ScreenSize", Float2),
                ("Exposure", Float1),
                ("BloomThreshold", Float1),
            ],
            &[],
            false,
        )?;
        let ssao = material(
            FULLSCREEN_VERTEX,
            SSAO_FRAGMENT,
            &[
                ("TargetSize", Float2),
                ("TanHalfFov", Float2),
                ("Far", Float1),
                ("Radius", Float1),
            ],
            &["DepthTex"],
            false,
        )?;
        let blur = material(
            FULLSCREEN_VERTEX,
            BLUR_FRAGMENT,
            &[
                ("TargetSize", Float2),
                ("SourceTexel", Float2),
                ("Direction", Float2),
                ("Mode", Float1),
            ],
            &["Source"],
            false,
        )?;
        let composite = material(
            FULLSCREEN_VERTEX,
            COMPOSITE_FRAGMENT,
            &[("TargetSize", Float2), ("BloomIntensity", Float1)],
            &["Scene", "Bloom"],
            false,
        )?;
        let shadow_resolution = tuning.shadow_resolution as u32;
        let shadows = (0..CASCADES)
            .map(|_| {
                target(
                    shadow_resolution,
                    shadow_resolution,
                    true,
                    FilterMode::Nearest,
                )
            })
            .collect();
        Ok(Self {
            lit,
            depth,
            sky,
            ssao,
            blur,
            composite,
            shadows,
            shadow_resolution,
            targets: None,
            view: None,
        })
    }

    fn ensure_targets(&mut self) -> (u32, u32) {
        let scale = screen_dpi_scale();
        let size = (
            (screen_width() * scale).round().max(1.) as u32,
            (screen_height() * scale).round().max(1.) as u32,
        );
        if self.targets.as_ref().is_none_or(|t| t.size != size) {
            let (w, h) = size;
            let (hw, hh) = ((w / 2).max(1), (h / 2).max(1));
            let (qw, qh) = ((w / 4).max(1), (h / 4).max(1));
            self.targets = Some(Targets {
                size,
                scene: target(w, h, true, FilterMode::Linear),
                depth: target(hw, hh, true, FilterMode::Nearest),
                ao: target(hw, hh, false, FilterMode::Linear),
                ao_blur: target(hw, hh, false, FilterMode::Linear),
                bloom_a: target(qw, qh, false, FilterMode::Linear),
                bloom_b: target(qw, qh, false, FilterMode::Linear),
            });
        }
        size
    }

    fn fullscreen(&self, material: &Material, pass: Option<RenderPass>) {
        set_camera(&ScreenPass { pass });
        gl_use_material(material);
        draw_rectangle(0., 0., 1., 1., WHITE);
        gl_use_default_material();
    }

    /// Render sky and lit world into the scene target. `geometry` draws world
    /// meshes with albedo vertex colors and normals (it is called once per
    /// shadow cascade, once for depth and once lit). On return the world camera
    /// targets the scene, so unlit overlays can be drawn before `finish`.
    pub fn render_world(
        &mut self,
        view: FrameView,
        tuning: &LightingTuning,
        geometry: &mut dyn FnMut(),
    ) {
        let env = LightEnvironment::new(tuning);
        let (w, h) = self.ensure_targets();
        let targets = self.targets.as_ref().expect("targets");
        let far = view.far;

        // 1. Cascaded shadow maps.
        let splits = cascade_splits(view.near.max(0.05), tuning.shadow_distance, CASCADES, 0.8);
        let resolution = self.shadow_resolution as f32;
        let mut matrices = [Mat4::IDENTITY; CASCADES];
        let mut texels = [0.; CASCADES];
        for i in 0..CASCADES {
            let m = fit_cascade(
                view.eye,
                view.forward,
                view.up,
                view.fovy,
                view.aspect,
                splits[i],
                splits[i + 1],
                env.sun_direction,
                resolution,
                SHADOW_DEPTH_RANGE,
            );
            matrices[i] = m;
            // World size of one shadow texel (ortho width / resolution).
            texels[i] = 2. / m.x_axis.truncate().length() / resolution;
            set_camera(&MatrixCamera {
                matrix: m,
                pass: self.shadows[i].render_pass.clone(),
            });
            clear_background(WHITE);
            self.depth.set_uniform("Mode", 0f32);
            self.depth.set_uniform("Far", far);
            gl_use_material(&self.depth);
            geometry();
            gl_use_default_material();
        }

        // 2. Half-resolution linear depth prepass, SSAO and blur.
        set_camera(&view.camera(&targets.depth));
        clear_background(WHITE);
        self.depth.set_uniform("Mode", 1f32);
        self.depth.set_uniform("Far", far);
        gl_use_material(&self.depth);
        geometry();
        gl_use_default_material();
        let (hw, hh) = (
            targets.depth.texture.width(),
            targets.depth.texture.height(),
        );
        let tan_y = (view.fovy * 0.5).tan();
        self.ssao
            .set_texture("DepthTex", targets.depth.texture.clone());
        self.ssao.set_uniform("TargetSize", vec2(hw, hh));
        self.ssao
            .set_uniform("TanHalfFov", vec2(tan_y * view.aspect, tan_y));
        self.ssao.set_uniform("Far", far);
        self.ssao.set_uniform("Radius", tuning.ao_radius);
        self.fullscreen(&self.ssao, Some(targets.ao.render_pass.clone()));
        self.blur.set_texture("Source", targets.ao.texture.clone());
        self.blur.set_uniform("TargetSize", vec2(hw, hh));
        self.blur.set_uniform("SourceTexel", vec2(1. / hw, 1. / hh));
        self.blur.set_uniform("Direction", Vec2::ZERO);
        self.blur.set_uniform("Mode", 0f32);
        self.fullscreen(&self.blur, Some(targets.ao_blur.render_pass.clone()));

        // 3. Sky.
        let screen = vec2(w as f32, h as f32);
        let view_projection = view.view_projection();
        set_camera(&ScreenPass {
            pass: Some(targets.scene.render_pass.clone()),
        });
        clear_background(BLACK);
        let sky = &self.sky;
        sky.set_uniform("InvViewProj", view_projection.inverse());
        sky.set_uniform("CameraPos", view.eye);
        sky.set_uniform("SunDir", env.sun_direction);
        sky.set_uniform("SunColor", env.sun_color);
        sky.set_uniform("SkyColor", env.sky_color);
        sky.set_uniform("HorizonColor", env.horizon_color);
        sky.set_uniform("GroundColor", env.ground_color);
        sky.set_uniform("ScreenSize", screen);
        sky.set_uniform("Exposure", env.exposure);
        sky.set_uniform("BloomThreshold", tuning.bloom_threshold);
        gl_use_material(sky);
        draw_rectangle(0., 0., 1., 1., WHITE);
        gl_use_default_material();

        // 4. Lit world.
        let lit = &self.lit;
        for (i, name) in ["ShadowMat0", "ShadowMat1", "ShadowMat2"]
            .iter()
            .enumerate()
        {
            lit.set_uniform(name, matrices[i]);
        }
        lit.set_uniform("CascadeEnds", vec3(splits[1], splits[2], splits[3]));
        lit.set_uniform("CascadeTexel", vec3(texels[0], texels[1], texels[2]));
        lit.set_uniform("ShadowSoftness", tuning.shadow_softness);
        lit.set_uniform("ShadowMapTexel", 1. / resolution);
        lit.set_uniform("DepthScale", 1. / (2. * SHADOW_DEPTH_RANGE));
        lit.set_uniform("SunDir", env.sun_direction);
        lit.set_uniform("SunColor", env.sun_color);
        lit.set_uniform("SkyColor", env.sky_color);
        lit.set_uniform("GroundColor", env.ground_color);
        lit.set_uniform("HorizonColor", env.horizon_color);
        lit.set_uniform("CameraPos", view.eye);
        lit.set_uniform("CameraForward", view.forward.normalize());
        lit.set_uniform("Exposure", env.exposure);
        lit.set_uniform("Roughness", env.roughness);
        lit.set_uniform(
            "Fog",
            vec4(
                tuning.fog_density,
                tuning.fog_falloff,
                tuning.fog_height,
                tuning.fog_max_opacity,
            ),
        );
        lit.set_uniform("ScreenSize", screen);
        lit.set_uniform("AoStrength", tuning.ao_strength.min(1.));
        lit.set_uniform("BloomThreshold", tuning.bloom_threshold);
        for (i, name) in ["Shadow0", "Shadow1", "Shadow2"].iter().enumerate() {
            lit.set_texture(name, self.shadows[i].texture.clone());
        }
        lit.set_texture("AoTex", targets.ao_blur.texture.clone());
        set_camera(&view.camera(&targets.scene));
        gl_use_material(lit);
        geometry();
        gl_use_default_material();
        self.view = Some(view);
    }

    /// Bloom and composite the scene to the screen.
    pub fn finish(&mut self, tuning: &LightingTuning) {
        let Some(targets) = self.targets.as_ref() else {
            return;
        };
        let (w, h) = targets.size;
        let (qw, qh) = (
            targets.bloom_a.texture.width(),
            targets.bloom_a.texture.height(),
        );
        let blur = &self.blur;
        // Bright pass into quarter resolution, then separable blur twice.
        blur.set_texture("Source", targets.scene.texture.clone());
        blur.set_uniform("TargetSize", vec2(qw, qh));
        blur.set_uniform("SourceTexel", vec2(1. / w as f32, 1. / h as f32));
        blur.set_uniform("Mode", 1f32);
        self.fullscreen(blur, Some(targets.bloom_a.render_pass.clone()));
        for _ in 0..2 {
            for (source, dest, direction) in [
                (&targets.bloom_a, &targets.bloom_b, vec2(1., 0.)),
                (&targets.bloom_b, &targets.bloom_a, vec2(0., 1.)),
            ] {
                blur.set_texture("Source", source.texture.clone());
                blur.set_uniform("TargetSize", vec2(qw, qh));
                blur.set_uniform("SourceTexel", vec2(1. / qw, 1. / qh));
                blur.set_uniform("Direction", direction);
                blur.set_uniform("Mode", 2f32);
                self.fullscreen(blur, Some(dest.render_pass.clone()));
            }
        }
        self.composite
            .set_texture("Scene", targets.scene.texture.clone());
        self.composite
            .set_texture("Bloom", targets.bloom_a.texture.clone());
        self.composite
            .set_uniform("TargetSize", vec2(w as f32, h as f32));
        self.composite
            .set_uniform("BloomIntensity", tuning.bloom_intensity);
        self.fullscreen(&self.composite, None);
        set_default_camera();
    }
}
