struct ProbeOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) @interpolate(flat) clip: vec4<f32>,
    @location(1) @interpolate(flat) color: vec4<f32>,
};
@vertex fn probe_vertex(input: __INPUT__, @builtin(vertex_index) index: u32) -> ProbeOutput {
    let actual = __ENTRY__(input);
    var output: ProbeOutput;
    output.position = vec4<f32>((f32(index) + 0.5) * (2.0 / __COUNT__.0) - 1.0, 0.0, 0.0, 1.0);
    output.clip = actual.position;
    output.color = actual.color;
    return output;
}
struct ProbeWords { @location(0) clip: vec4<u32>, @location(1) color: vec4<u32>, };
@fragment fn probe_fragment(input: ProbeOutput) -> ProbeWords {
    var output: ProbeWords;
    output.clip = bitcast<vec4<u32>>(input.clip);
    output.color = bitcast<vec4<u32>>(input.color);
    return output;
}
