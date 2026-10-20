//! Opt-in submission counters and real GPU timestamp queries.
//!
//! CPU wall time is deliberately owned by the caller. Timestamp readback is an
//! explicit fence, never inserted into normal gameplay or inferred from CPU time.

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrameMetrics {
    /// Actual draw_indexed calls, including an optional presentation quad.
    pub draw_calls: u64,
    /// Submitted triangle primitives, not visible pixels or unique triangles.
    pub triangles: u64,
    pub line_segments: u64,
    /// Uploaded payload bytes. Transform alignment bytes count; GPU allocation
    /// padding, initialization resources, and readback traffic do not.
    pub vertex_upload_bytes: u64,
    pub index_upload_bytes: u64,
    pub uniform_upload_bytes: u64,
    pub texture_upload_bytes: u64,
    /// Elapsed GPU ticks converted with Queue::get_timestamp_period. Unavailable
    /// until explicit readback, or when the adapter lacks encoder timestamps.
    pub gpu_timestamp_ns: Option<f64>,
}
impl FrameMetrics {
    pub(crate) fn record_draw(&mut self, indices: u32, lines: bool) {
        self.draw_calls += 1;
        if lines {
            self.line_segments += u64::from(indices / 2);
        } else {
            self.triangles += u64::from(indices / 3);
        }
    }
    pub fn upload_bytes(&self) -> u64 {
        self.vertex_upload_bytes
            + self.index_upload_bytes
            + self.uniform_upload_bytes
            + self.texture_upload_bytes
    }
}

pub(super) fn timestamp_features() -> wgpu::Features {
    wgpu::Features::TIMESTAMP_QUERY | wgpu::Features::TIMESTAMP_QUERY_INSIDE_ENCODERS
}

pub(super) struct TimestampQueries {
    query: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    readback: wgpu::Buffer,
    pending: bool,
}
impl TimestampQueries {
    pub fn new(device: &wgpu::Device) -> Option<Self> {
        if !device.features().contains(timestamp_features()) {
            return None;
        }
        Some(Self {
            query: device.create_query_set(&wgpu::QuerySetDescriptor {
                label: Some("opt-in frame timestamps"),
                ty: wgpu::QueryType::Timestamp,
                count: 2,
            }),
            resolve: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("frame timestamp resolve"),
                size: 16,
                usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }),
            readback: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("frame timestamp readback"),
                size: 16,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            }),
            pending: false,
        })
    }
    pub fn begin(&self, encoder: &mut wgpu::CommandEncoder) -> Result<(), String> {
        if self.pending {
            return Err("profiled frame requires wait_for_frame before the next submission".into());
        }
        encoder.write_timestamp(&self.query, 0);
        Ok(())
    }
    pub fn end(&mut self, encoder: &mut wgpu::CommandEncoder) {
        encoder.write_timestamp(&self.query, 1);
        encoder.resolve_query_set(&self.query, 0..2, &self.resolve, 0);
        encoder.copy_buffer_to_buffer(&self.resolve, 0, &self.readback, 0, 16);
        self.pending = true;
    }
    pub fn finish(&mut self, device: &wgpu::Device, period: f32) -> Result<Option<f64>, String> {
        if !self.pending {
            return Ok(None);
        }
        let (sender, receiver) = std::sync::mpsc::channel();
        self.readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = sender.send(result);
            });
        wait(device)?;
        receiver
            .recv()
            .map_err(|e| e.to_string())?
            .map_err(|e| format!("timestamp map: {e}"))?;
        let mapped = self
            .readback
            .slice(..)
            .get_mapped_range()
            .map_err(|e| format!("timestamp mapped range: {e}"))?;
        let start = u64::from_le_bytes(mapped[0..8].try_into().unwrap());
        let end = u64::from_le_bytes(mapped[8..16].try_into().unwrap());
        drop(mapped);
        self.readback.unmap();
        self.pending = false;
        // Timestamp wrap/reset or invalid period is unavailable, never zero or
        // CPU-derived substitute evidence.
        Ok(timestamp_duration(start, end, period))
    }
}
fn timestamp_duration(start: u64, end: u64, period: f32) -> Option<f64> {
    (end > start && period.is_finite() && period > 0.)
        .then(|| (end - start) as f64 * f64::from(period))
}
pub(super) fn wait(device: &wgpu::Device) -> Result<(), String> {
    device
        .poll(wgpu::PollType::Wait {
            submission_index: None,
            timeout: Some(std::time::Duration::from_secs(120)),
        })
        .map(|_| ())
        .map_err(|e| format!("benchmark GPU completion: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn issued_counts_distinguish_lines_and_triangles() {
        let mut m = FrameMetrics::default();
        m.record_draw(12, false);
        m.record_draw(8, true);
        assert_eq!((m.draw_calls, m.triangles, m.line_segments), (2, 4, 4));
        assert_eq!(m.gpu_timestamp_ns, None);
        m.vertex_upload_bytes = 120;
        m.index_upload_bytes = 6;
        m.uniform_upload_bytes = 320;
        m.texture_upload_bytes = 4;
        assert_eq!(m.upload_bytes(), 450);
    }
    #[test]
    #[ignore = "requires an actual WGPU adapter; run explicitly for native/software evidence"]
    fn headless_metrics_count_real_issued_work_and_payloads() {
        use crate::draw::{BlendMode, Camera, Color, DrawList, Mesh, Renderer, Vertex};
        use crate::render::{BackendSelection, WgpuRenderer};
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless_profiled(
            32,
            32,
            BackendSelection::Auto,
            false,
        ))
        .unwrap();
        let mesh = Mesh {
            vertices: vec![
                Vertex::new(0., 0., 0., 0., 0., Color::WHITE),
                Vertex::new(16., 0., 0., 0., 0., Color::WHITE),
                Vertex::new(0., 16., 0., 0., 0., Color::WHITE),
            ],
            indices: vec![0, 1, 2],
            texture: None,
        };
        let mut list = DrawList::new(32, 32);
        list.camera(Camera::screen(32, 32));
        list.draw_mesh(&mesh, glam::Mat4::IDENTITY, BlendMode::Opaque);
        for _ in 0..2 {
            renderer.submit(&list).unwrap();
            renderer.wait_for_frame().unwrap();
            let m = renderer.last_frame_metrics().unwrap();
            assert_eq!((m.draw_calls, m.triangles, m.line_segments), (1, 1, 0));
            assert_eq!(
                (
                    m.vertex_upload_bytes,
                    m.index_upload_bytes,
                    m.uniform_upload_bytes,
                    m.texture_upload_bytes
                ),
                (120, 6, 64, 0)
            );
            if let Some(ns) = m.gpu_timestamp_ns {
                assert!(ns > 0. && ns.is_finite());
            }
            assert!(m.gpu_timestamp_ns.is_none() || renderer.gpu_timestamps_available());
        }
    }
    #[test]
    fn timestamp_requires_valid_monotonic_ticks() {
        assert_eq!(timestamp_duration(10, 30, 2.5), Some(50.));
        assert_eq!(timestamp_duration(30, 10, 1.), None);
        assert_eq!(timestamp_duration(10, 10, 1.), None);
        assert_eq!(timestamp_duration(10, 30, f32::NAN), None);
        assert_eq!(timestamp_duration(10, 30, 0.), None);
    }
}
