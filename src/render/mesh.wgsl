struct Transform { mvp: mat4x4<f32>, };
@group(0) @binding(0) var<uniform> transform: Transform;
@group(1) @binding(0) var color_texture: texture_2d<f32>;
@group(1) @binding(1) var color_sampler: sampler;
struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) uv: vec2<f32>,
    @location(2) color: vec4<f32>,
    @location(3) normal: vec4<f32>,
};
struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) color: vec4<f32>,
};
@vertex fn vs_main(input: VertexInput) -> VertexOutput {
    var output: VertexOutput;
    output.position = transform.mvp * vec4<f32>(input.position,1.0);
    output.uv = input.uv;
    output.color = input.color;
    return output;
}
@fragment fn fs_straight(input: VertexOutput) -> @location(0) vec4<f32> {
    // Uploaded images/glyphs and CPU-lit vertex colors are straight RGBA.
    // The blend unit applies the combined source alpha once.
    return textureSample(color_texture,color_sampler,input.uv) * input.color;
}
@fragment fn fs_associate_straight(input: VertexOutput) -> @location(0) vec4<f32> {
    // Opaque means replace rather than blend. Replacement still obeys target
    // storage representation even for images/vertices with fractional alpha.
    let straight = textureSample(color_texture,color_sampler,input.uv) * input.color;
    return vec4<f32>(straight.rgb * straight.a, straight.a);
}
@fragment fn fs_associated(input: VertexOutput) -> @location(0) vec4<f32> {
    // Target RGB is already associated with its coverage and may also contain
    // additive emission at alpha zero. Never divide by or multiply by sample.a.
    // Tint opacity attenuates both radiance and coverage exactly once.
    let sampled = textureSample(color_texture,color_sampler,input.uv);
    return vec4<f32>(sampled.rgb * input.color.rgb * input.color.a,
                     sampled.a * input.color.a);
}
@fragment fn fs_present(input: VertexOutput) -> @location(0) vec4<f32> {
    // Present associated RGB over black as an opaque display image, including
    // additive emission. This matches the default framebuffer PNG contract.
    let sampled = textureSample(color_texture,color_sampler,input.uv);
    return vec4<f32>(sampled.rgb, 1.0);
}
