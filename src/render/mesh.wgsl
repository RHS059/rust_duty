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
@fragment fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    // Vertex colors already contain SceneLighting's CPU lighting.
    return textureSample(color_texture,color_sampler,input.uv) * input.color;
}
