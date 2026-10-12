// Immutable model-space vertices; only these per-draw/pose uniforms change.
struct DrawState {
    view_projection: mat4x4<f32>,
    root: mat4x4<f32>,
    normal: mat4x4<f32>,
    light: vec4<f32>, // direction toward light, ambient
    material: vec4<f32>, // immutable RGB albedo, diffuse
    alpha: vec4<f32>, // rounded actor alpha byte / 255, remaining fields reserved
};
struct Palette {
    positions: array<mat4x4<f32>, 128>,
    normals: array<mat4x4<f32>, 128>,
};
@group(0) @binding(0) var<uniform> draw: DrawState;
@group(1) @binding(0) var color_texture: texture_2d<f32>;
@group(1) @binding(1) var color_sampler: sampler;
@group(2) @binding(0) var<uniform> palette: Palette;

struct RigidInput {
    @location(0) position: vec3<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) normal: vec3<f32>,
};
struct SkinInput {
    @location(0) position: vec3<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) normal: vec3<f32>,
    @location(3) joints0: vec4<u32>,
    @location(4) joints1: vec4<u32>,
    @location(5) weights0: vec4<f32>,
    @location(6) weights1: vec4<f32>,
};
struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) color: vec4<f32>,
};

fn normal_or_y(value: vec3<f32>) -> vec3<f32> {
    let length_squared = dot(value, value);
    // Match glam::try_normalize: even finite inputs can overflow dot(), or
    // underflow its reciprocal. Zero/nonfinite reciprocals use the +Y fallback.
    if length_squared > 0.0 && length_squared <= 3.4028234663852886e38 {
        let reciprocal = inverseSqrt(length_squared);
        if reciprocal > 0.0 && reciprocal <= 3.4028234663852886e38 {
            return value * reciprocal;
        }
    }
    return vec3<f32>(0.0, 1.0, 0.0);
}

fn color_byte(value: f32) -> f32 {
    // Rust's float-to-u8 conversion saturates infinities and maps NaN to zero.
    if value >= 1.0 { return 1.0; }
    if value > 0.0 { return floor(value * 255.0) / 255.0; }
    return 0.0;
}
fn lit_vertex_rgb(normal: vec3<f32>) -> vec3<f32> {
    let product = dot(normal_or_y(normal), draw.light.xyz);
    var directional = 0.0;
    if product > 0.0 { directional = product; }
    let irradiance = draw.light.w + draw.material.w * directional;
    // The existing CPU path saturates/truncates RGBA8 BEFORE interpolation.
    // Keep this vertex-stage quantization rather than changing the material.
    let value = draw.material.rgb * irradiance;
    return vec3<f32>(color_byte(value.r), color_byte(value.g), color_byte(value.b));
}

@vertex fn vs_rigid(input: RigidInput) -> VertexOutput {
    var output: VertexOutput;
    output.position = draw.view_projection * vec4<f32>(input.position, 1.0);
    output.uv = input.uv;
    output.color = vec4<f32>(lit_vertex_rgb((draw.normal * vec4<f32>(input.normal, 0.0)).xyz), draw.alpha.x);
    return output;
}

@vertex fn vs_skin(input: SkinInput) -> VertexOutput {
    var position = vec3<f32>(0.0);
    var normal = vec3<f32>(0.0);
    // Preserve all eight ordered influences; do not renormalize source weights.
    for (var i = 0u; i < 4u; i++) {
        let weight = input.weights0[i];
        if weight > 0.0 {
            position += (palette.positions[input.joints0[i]] * vec4<f32>(input.position, 1.0)).xyz * weight;
            normal += (palette.normals[input.joints0[i]] * vec4<f32>(input.normal, 0.0)).xyz * weight;
        }
    }
    for (var i = 0u; i < 4u; i++) {
        let weight = input.weights1[i];
        if weight > 0.0 {
            position += (palette.positions[input.joints1[i]] * vec4<f32>(input.position, 1.0)).xyz * weight;
            normal += (palette.normals[input.joints1[i]] * vec4<f32>(input.normal, 0.0)).xyz * weight;
        }
    }
    var output: VertexOutput;
    let world_position = (draw.root * vec4<f32>(position, 1.0)).xyz;
    output.position = draw.view_projection * vec4<f32>(world_position, 1.0);
    output.uv = input.uv;
    // The original skin route normalizes here and again inside irradiance.
    let posed_normal = normal_or_y((draw.root * vec4<f32>(normal, 0.0)).xyz);
    output.color = vec4<f32>(lit_vertex_rgb(posed_normal), 1.0);
    return output;
}

@fragment fn fs_straight(input: VertexOutput) -> @location(0) vec4<f32> {
    return textureSample(color_texture,color_sampler,input.uv) * input.color;
}
@fragment fn fs_associate_straight(input: VertexOutput) -> @location(0) vec4<f32> {
    let straight = textureSample(color_texture,color_sampler,input.uv) * input.color;
    return vec4<f32>(straight.rgb * straight.a, straight.a);
}
