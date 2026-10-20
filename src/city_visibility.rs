//! Conservative whole-floor cell/portal visibility. Missing or invalid authored
//! topology disables this optimization; no collision box becomes an occluder.
use super::{json_vec3, Frustum, StaticCityChunk};
use crate::sim::Aabb;
use glam::Vec3;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

const MAX_CELLS: usize = 1024;
const MAX_PORTALS: usize = 16384;
// Match the authored topology validator's positional tolerance.
const PORTAL_BOUNDARY_TOLERANCE: f32 = 0.0001;
const BOUNDARY_MARGIN: f32 = 0.08;
const CAMERA_PORTAL_MARGIN: f32 = 0.25;

struct Cell {
    bounds: Aabb,
    building: String,
}
struct Portal {
    from: usize,
    to: usize,
    bounds: Aabb,
    normal: Vec3,
}
pub(super) struct InteriorVisibility {
    cells: Vec<Cell>,
    portals: Vec<Portal>,
    adjacency: Vec<Vec<usize>>,
    assignments: Vec<Option<usize>>,
}
pub(super) struct FrameVisibility {
    visible: [bool; MAX_CELLS + 1],
}
impl InteriorVisibility {
    pub(super) fn from_manifest(manifest: &Value, chunks: &[StaticCityChunk]) -> Option<Self> {
        Self::parse(manifest, chunks).ok()
    }
    fn parse(manifest: &Value, chunks: &[StaticCityChunk]) -> Result<Self, String> {
        let value = &manifest["visibility"];
        if value["schema"].as_str() != Some("rust-duty-city-visibility/v1")
            || value["complete"].as_bool() != Some(true)
        {
            return Err("visibility topology is absent or incomplete".into());
        }
        let records = value["cells"]
            .as_array()
            .filter(|v| !v.is_empty() && v.len() <= MAX_CELLS)
            .ok_or("invalid cell count")?;
        let mut ids = HashMap::new();
        let mut cells = Vec::new();
        for (index, record) in records.iter().enumerate() {
            let id = record["id"]
                .as_str()
                .filter(|s| !s.is_empty() && s.len() < 128)
                .ok_or("invalid cell id")?;
            if ids.insert(id.to_owned(), index).is_some() {
                return Err("duplicate cell id".into());
            }
            let building = record["building"]
                .as_str()
                .filter(|s| !s.is_empty() && s.len() < 128)
                .ok_or("invalid cell building")?
                .to_owned();
            let bounds = read_bounds(record)?;
            if !bounds.min.cmplt(bounds.max).all() {
                return Err("flat cell".into());
            }
            cells.push(Cell { bounds, building });
        }
        // Ambiguous overlapping interiors cannot provide a safe camera cell.
        for (index, cell) in cells.iter().enumerate() {
            if cells[index + 1..]
                .iter()
                .any(|other| cell.bounds.overlaps(other.bounds))
            {
                return Err("overlapping visibility cells".into());
            }
        }
        let records = value["portals"]
            .as_array()
            .filter(|v| !v.is_empty() && v.len() <= MAX_PORTALS)
            .ok_or("invalid portal count")?;
        if value["portal_count"].as_u64() != Some(records.len() as u64) {
            return Err("incomplete portal table".into());
        }
        let exterior = cells.len();
        let mut portals = Vec::new();
        let mut adjacency = vec![Vec::new(); cells.len() + 1];
        let mut seen_portals = HashSet::new();
        for record in records {
            let from = *ids
                .get(record["from"].as_str().ok_or("missing source cell")?)
                .ok_or("unknown source cell")?;
            let destination = record.get("to").ok_or("missing target cell")?;
            let to = if destination.is_null() {
                exterior
            } else {
                *ids.get(destination.as_str().ok_or("invalid target cell")?)
                    .ok_or("unknown target cell")?
            };
            if from == to {
                return Err("self portal".into());
            }
            let bounds = read_bounds(record)?;
            let normal = json_vec3(&record["normal"], "portal.normal")?;
            if normal.abs().max_element() != 1. || normal.abs().element_sum() != 1. {
                return Err("portal normal must be unit axis".into());
            }
            let size = bounds.size();
            if (normal.x == 0. && size.x <= 0.)
                || (normal.y == 0. && size.y <= 0.)
                || (normal.z == 0. && size.z <= 0.)
            {
                return Err("degenerate portal opening".into());
            }
            let center = bounds.center();
            let axis = if normal.x != 0. {
                0
            } else if normal.y != 0. {
                1
            } else {
                2
            };
            let on_boundary = |cell: Aabb, outward: f32| {
                let boundary = if outward > 0. {
                    cell.max[axis]
                } else {
                    cell.min[axis]
                };
                (center[axis] - boundary).abs() <= PORTAL_BOUNDARY_TOLERANCE
            };
            if !on_boundary(cells[from].bounds, normal[axis])
                || to != exterior && !on_boundary(cells[to].bounds, -normal[axis])
            {
                return Err("portal plane does not match connected cell boundaries".into());
            }
            if normal.dot(cells[from].bounds.center() - center) >= -BOUNDARY_MARGIN
                || to != exterior
                    && normal.dot(cells[to].bounds.center() - center) <= BOUNDARY_MARGIN
            {
                return Err("portal orientation disagrees with cells".into());
            }
            if !touches(bounds, cells[from].bounds)
                || to != exterior && !touches(bounds, cells[to].bounds)
            {
                return Err("portal outside connected cells".into());
            }
            let bits = |vector: Vec3| {
                vector
                    .to_array()
                    .map(|value| if value == 0. { 0 } else { value.to_bits() })
            };
            if !seen_portals.insert((from, to, bits(bounds.min), bits(bounds.max), bits(normal))) {
                return Err("duplicate visibility portal".into());
            }
            let index = portals.len();
            portals.push(Portal {
                from,
                to,
                bounds,
                normal,
            });
            adjacency[from].push(index);
            adjacency[to].push(index);
        }
        // Every cell is explicitly opened by the exporter; a missing entry does
        // not silently create a sealed volume capable of hiding its contents.
        if adjacency[..exterior].iter().any(Vec::is_empty) {
            return Err("cell has no verified opening".into());
        }
        let assignments = chunks
            .iter()
            .map(|chunk| {
                let building = chunk.instance.as_ref()?.building.as_deref()?;
                cells.iter().position(|cell| {
                    cell.building == building && contains_geometry(cell.bounds, chunk.bounds)
                })
            })
            .collect();
        Ok(Self {
            cells,
            portals,
            adjacency,
            assignments,
        })
    }
    pub(super) fn frame(&self, eye: Vec3, frustum: &Frustum) -> FrameVisibility {
        let all = || FrameVisibility {
            visible: [true; MAX_CELLS + 1],
        };
        if !eye.is_finite() {
            return all();
        }
        if self
            .portals
            .iter()
            .any(|p| contains(p.bounds, eye, -CAMERA_PORTAL_MARGIN))
        {
            return all();
        }
        let mut start = self.cells.len();
        for (index, cell) in self.cells.iter().enumerate() {
            if contains(cell.bounds, eye, -BOUNDARY_MARGIN) {
                if !contains(cell.bounds, eye, BOUNDARY_MARGIN) {
                    return all();
                }
                start = index;
            }
        }
        let mut result = FrameVisibility {
            visible: [false; MAX_CELLS + 1],
        };
        let mut queue = [0_usize; MAX_CELLS + 1];
        queue[0] = start;
        result.visible[start] = true;
        let (mut head, mut tail) = (0, 1);
        while head < tail {
            let current = queue[head];
            head += 1;
            for &index in &self.adjacency[current] {
                let portal = &self.portals[index];
                let next = if current == portal.from {
                    portal.to
                } else {
                    portal.from
                };
                if result.visible[next] {
                    continue;
                }
                let source_side = if current == portal.from { -1. } else { 1. };
                if portal.normal.dot(eye - portal.bounds.center()) * source_side < -BOUNDARY_MARGIN
                    || !frustum.intersects_portal(portal.bounds)
                {
                    continue;
                }
                result.visible[next] = true;
                queue[tail] = next;
                tail += 1;
            }
        }
        result
    }
    pub(super) fn record_visible(&self, record: usize, frame: &FrameVisibility) -> bool {
        self.assignments[record].is_none_or(|cell| frame.visible[cell])
    }
}
fn read_bounds(value: &Value) -> Result<Aabb, String> {
    let bounds = Aabb {
        min: json_vec3(&value["min"], "visibility.min")?,
        max: json_vec3(&value["max"], "visibility.max")?,
    };
    if !bounds.min.cmple(bounds.max).all() {
        return Err("inverted visibility bounds".into());
    }
    Ok(bounds)
}
fn contains(bounds: Aabb, point: Vec3, margin: f32) -> bool {
    point.cmpge(bounds.min + Vec3::splat(margin)).all()
        && point.cmple(bounds.max - Vec3::splat(margin)).all()
}
fn contains_geometry(outer: Aabb, inner: Aabb) -> bool {
    // Furniture rests on the cell floor. Permit lower-face contact, but never
    // cross it; retain horizontal/ceiling margins for shell and straddlers.
    let lower = outer.min + Vec3::new(BOUNDARY_MARGIN, 0., BOUNDARY_MARGIN);
    let upper = outer.max - Vec3::splat(BOUNDARY_MARGIN);
    inner.min.cmpge(lower).all() && inner.max.cmple(upper).all()
}
fn touches(a: Aabb, b: Aabb) -> bool {
    a.min.cmple(b.max + Vec3::splat(BOUNDARY_MARGIN)).all()
        && a.max.cmpge(b.min - Vec3::splat(BOUNDARY_MARGIN)).all()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::city_level::InstanceMetadata;
    use crate::draw::{Color, StaticMesh, Vertex};
    use glam::{Mat4, Vec2};

    fn chunk(center: Vec3, building: Option<&str>) -> StaticCityChunk {
        let bounds = Aabb::from_center(center, Vec3::splat(0.2));
        let positions = [
            bounds.min,
            bounds.max,
            Vec3::new(bounds.min.x, bounds.max.y, bounds.min.z),
        ];
        StaticCityChunk {
            bounds,
            lods: [None, None],
            mesh: StaticMesh::new(
                positions
                    .into_iter()
                    .map(|p| Vertex::new2(p, Vec2::ZERO, Color::WHITE))
                    .collect(),
                vec![0, 1, 2],
                None,
            )
            .unwrap(),
            instance: Some(InstanceMetadata {
                id: 0,
                asset: "synthetic-prop".into(),
                building: building.map(str::to_owned),
                max_distance: 0.,
            }),
        }
    }
    fn manifest(front_door: bool, stairs: bool) -> Value {
        let mut cells =
            vec![serde_json::json!({"id":"A:0","building":"A","min":[-2,0,-12],"max":[2,4,-8]})];
        let mut portals = vec![
            serde_json::json!({"from":"A:0","to":null,"min":[-0.6,0,-12.01],"max":[0.6,2.3,-11.99],"normal":[0,0,-1]}),
        ];
        if front_door {
            portals.push(serde_json::json!({"from":"A:0","to":null,"min":[-0.6,0,-8.01],"max":[0.6,2.3,-7.99],"normal":[0,0,1]}));
        }
        if stairs {
            cells.push(
                serde_json::json!({"id":"A:1","building":"A","min":[-2,4,-12],"max":[2,8,-8]}),
            );
            portals.push(serde_json::json!({"from":"A:0","to":"A:1","min":[-1,3.99,-11],"max":[1,4.01,-9],"normal":[0,1,0]}));
        }
        serde_json::json!({"visibility":{"schema":"rust-duty-city-visibility/v1","complete":true,"cells":cells,"portal_count":portals.len(),"portals":portals}})
    }
    fn frustum(eye: Vec3, direction: Vec3, up: Vec3) -> Frustum {
        Frustum::new(
            Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 0.035, 400.)
                * Mat4::look_at_rh(eye, eye + direction, up),
        )
    }
    #[test]
    fn solid_front_wall_hides_interior_but_never_shell_or_unknown_geometry() {
        let chunks = [
            chunk(Vec3::new(0., 2., -10.), Some("A")),
            chunk(Vec3::new(0., 2., -8.), Some("A")),
            chunk(Vec3::new(0., 2., -10.), None),
        ];
        let scene = InteriorVisibility::from_manifest(&manifest(false, false), &chunks).unwrap();
        let eye = Vec3::new(0., 2., 0.);
        let camera = frustum(eye, -Vec3::Z, Vec3::Y);
        assert!(
            camera.intersects(chunks[0].bounds),
            "test interior is within the camera frustum"
        );
        let frame = scene.frame(eye, &camera);
        assert!(
            !scene.record_visible(0, &frame),
            "a rear-facing window cannot reveal an interior through a solid front wall"
        );
        assert!(
            scene.record_visible(1, &frame),
            "shell/boundary geometry is never assigned"
        );
        assert!(
            scene.record_visible(2, &frame),
            "unclassified geometry fails open"
        );
        let scene = InteriorVisibility::from_manifest(&manifest(true, false), &chunks).unwrap();
        assert!(
            scene.record_visible(0, &scene.frame(eye, &camera)),
            "an actual doorway reveals the interior"
        );
    }
    #[test]
    fn floor_contact_furniture_is_assigned_but_crossing_surfaces_are_not() {
        let chunks = [
            chunk(Vec3::new(0., 0.1, -10.), Some("A")),
            chunk(Vec3::new(0., 0., -10.), Some("A")),
            chunk(Vec3::new(0., 3.95, -10.), Some("A")),
        ];
        let scene = InteriorVisibility::from_manifest(&manifest(false, false), &chunks).unwrap();
        assert_eq!(scene.assignments, [Some(0), None, None]);
        let eye = Vec3::new(0., 2., 0.);
        let frame = scene.frame(eye, &frustum(eye, -Vec3::Z, Vec3::Y));
        assert!(!scene.record_visible(0, &frame));
        assert!(scene.record_visible(1, &frame) && scene.record_visible(2, &frame));
    }

    #[test]
    fn all_four_exterior_opening_directions_preserve_visibility() {
        fn rotate(mut p: Vec3, turns: usize) -> Vec3 {
            for _ in 0..turns {
                p = Vec3::new(-p.z, p.y, p.x);
            }
            p
        }
        for turns in 0..4 {
            for open_front in [false, true] {
                let mut source = manifest(open_front, false);
                for field in ["cells", "portals"] {
                    for record in source["visibility"][field].as_array_mut().unwrap() {
                        let lo = rotate(json_vec3(&record["min"], "min").unwrap(), turns);
                        let hi = rotate(json_vec3(&record["max"], "max").unwrap(), turns);
                        record["min"] = serde_json::json!(lo.min(hi).to_array());
                        record["max"] = serde_json::json!(lo.max(hi).to_array());
                        if field == "portals" {
                            record["normal"] = serde_json::json!(rotate(
                                json_vec3(&record["normal"], "normal").unwrap(),
                                turns
                            )
                            .to_array());
                        }
                    }
                }
                let chunks = [chunk(rotate(Vec3::new(0., 2., -10.), turns), Some("A"))];
                let scene = InteriorVisibility::from_manifest(&source, &chunks).unwrap();
                let eye = Vec3::new(0., 2., 0.);
                let frame = scene.frame(eye, &frustum(eye, rotate(-Vec3::Z, turns), Vec3::Y));
                assert_eq!(
                    scene.record_visible(0, &frame),
                    open_front,
                    "direction {turns}: rear window alone cannot reveal interior"
                );
            }
        }
    }

    #[test]
    fn door_crossings_and_camera_inside_are_conservative() {
        let chunks = [
            chunk(Vec3::new(0., 2., -10.), Some("A")),
            chunk(Vec3::new(0., 6., -10.), Some("A")),
        ];
        let scene = InteriorVisibility::from_manifest(&manifest(true, true), &chunks).unwrap();
        for z in [-7.8, -8., -8.2] {
            let eye = Vec3::new(0., 1.7, z);
            let frame = scene.frame(eye, &frustum(eye, Vec3::X, Vec3::Y));
            assert!(
                scene.record_visible(0, &frame) && scene.record_visible(1, &frame),
                "door boundary fails open"
            );
        }
        let eye = Vec3::new(0., 1.7, -10.);
        assert!(scene.record_visible(0, &scene.frame(eye, &frustum(eye, Vec3::X, Vec3::Y))));
    }
    #[test]
    fn stairs_connect_floors_without_culling_near_plane_crossings() {
        let chunks = [
            chunk(Vec3::new(0., 2., -10.), Some("A")),
            chunk(Vec3::new(0., 6., -10.), Some("A")),
        ];
        let scene = InteriorVisibility::from_manifest(&manifest(false, true), &chunks).unwrap();
        let eye = Vec3::new(0., 1.7, -10.);
        let upward = frustum(eye, Vec3::new(0., 1., -0.1), Vec3::Z);
        let frame = scene.frame(eye, &upward);
        assert!(scene.record_visible(0, &frame) && scene.record_visible(1, &frame));
        let above = Vec3::new(0., 6., -10.);
        let frame = scene.frame(above, &frustum(above, Vec3::new(0., -1., -0.1), Vec3::Z));
        assert!(
            scene.record_visible(0, &frame),
            "stair traversal works downward too"
        );
        let eye = Vec3::new(0., 3.98, -10.);
        let frame = scene.frame(eye, &frustum(eye, Vec3::X, Vec3::Y));
        assert!(
            scene.record_visible(1, &frame),
            "eye crossing a stair portal cannot pop its destination"
        );
    }
    #[test]
    fn opening_before_camera_near_plane_still_reveals_geometry_beyond_it() {
        let chunks = [chunk(Vec3::new(0., 1.7, -10.), Some("A"))];
        let scene = InteriorVisibility::from_manifest(&manifest(true, false), &chunks).unwrap();
        let eye = Vec3::new(0., 1.7, -6.);
        let camera = Frustum::new(
            Mat4::perspective_rh_gl(60_f32.to_radians(), 16. / 9., 3., 400.)
                * Mat4::look_at_rh(eye, eye - Vec3::Z, Vec3::Y),
        );
        assert!(
            !camera.intersects(scene.portals[1].bounds),
            "opening is before the exaggerated near plane"
        );
        assert!(
            camera.intersects(chunks[0].bounds),
            "interior object is beyond the near plane"
        );
        assert!(
            scene.record_visible(0, &scene.frame(eye, &camera)),
            "portal testing omits the near-plane clip"
        );
    }

    #[test]
    fn portal_plane_must_match_its_source_boundary() {
        let target = Vec3::new(-1.75, 1.7, -8.5);
        let chunks = [chunk(target, Some("A"))];
        let mut source = manifest(true, false);
        let eye = Vec3::new(7., 1.7, -6.);
        let camera = Frustum::new(
            Mat4::perspective_rh_gl(5_f32.to_radians(), 16. / 9., 0.035, 400.)
                * Mat4::look_at_rh(eye, target, Vec3::Y),
        );
        assert!(camera.intersects(chunks[0].bounds));
        let scene = InteriorVisibility::from_manifest(&source, &chunks).unwrap();
        assert!(scene.record_visible(0, &scene.frame(eye, &camera)));

        source["visibility"]["portals"][1]["min"][2] = (-9.01).into();
        source["visibility"]["portals"][1]["max"][2] = (-8.99).into();
        assert!(
            !camera.intersects_portal(read_bounds(&source["visibility"]["portals"][1]).unwrap())
        );
        assert!(InteriorVisibility::from_manifest(&source, &chunks).is_none());
    }

    #[test]
    fn portal_plane_must_match_the_opposite_destination_boundary() {
        let chunks = [chunk(Vec3::new(0., 6., -10.), Some("A"))];
        let mut source = manifest(false, true);
        assert!(InteriorVisibility::from_manifest(&source, &chunks).is_some());
        // Still inside the broad adjacency margin, with no cell overlap, but
        // no longer the shared floor surface promised by this stair portal.
        source["visibility"]["cells"][1]["min"][1] = 4.04.into();
        assert!(InteriorVisibility::from_manifest(&source, &chunks).is_none());
    }

    #[test]
    fn shared_portal_boundary_allows_exporter_rounding_tolerance() {
        let chunks = [chunk(Vec3::new(0., 6., -10.), Some("A"))];
        let mut source = manifest(false, true);
        source["visibility"]["portals"][1]["min"][1] = 3.99005.into();
        source["visibility"]["portals"][1]["max"][1] = 4.01005.into();
        assert!(InteriorVisibility::from_manifest(&source, &chunks).is_some());
    }

    #[test]
    fn duplicate_portals_cannot_replace_a_real_opening_without_disabling_occlusion() {
        let chunks = [chunk(Vec3::new(0., 2., -10.), Some("A"))];
        let source = manifest(true, false);
        let eye = Vec3::new(0., 2., 0.);
        let camera = frustum(eye, -Vec3::Z, Vec3::Y);
        let scene = InteriorVisibility::from_manifest(&source, &chunks).unwrap();
        assert!(scene.record_visible(0, &scene.frame(eye, &camera)));
        for zero in [0., -0.] {
            let mut broken = source.clone();
            broken["visibility"]["portals"][1] = broken["visibility"]["portals"][0].clone();
            broken["visibility"]["portals"][1]["normal"][0] = serde_json::json!(zero);
            // The portal count and adjacency remain valid, but the actual
            // front doorway has been replaced by a duplicate rear opening.
            assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
        }
    }

    #[test]
    fn missing_stair_destination_disables_an_otherwise_connected_graph() {
        let chunks = [chunk(Vec3::new(0., 6., -10.), Some("A"))];
        let mut source = manifest(false, true);
        // Real authored upper floors have exterior windows, so losing the
        // stair edge must not rely on an isolated-cell check to fail open.
        source["visibility"]["portals"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::json!({"from":"A:1","to":null,"min":[-0.6,4.9,-12.01],"max":[0.6,6.3,-11.99],"normal":[0,0,-1]}));
        source["visibility"]["portal_count"] = 3.into();
        let eye = Vec3::new(0., 1.7, -10.);
        let camera = frustum(eye, Vec3::new(0., 1., -0.1), Vec3::Z);
        let scene = InteriorVisibility::from_manifest(&source, &chunks).unwrap();
        assert!(scene.record_visible(0, &scene.frame(eye, &camera)));

        // Explicit null remains a valid exterior destination. Missing data
        // cannot silently turn this interior connection into another opening.
        source["visibility"]["portals"][1]
            .as_object_mut()
            .unwrap()
            .remove("to");
        assert!(InteriorVisibility::from_manifest(&source, &chunks).is_none());
    }

    #[test]
    fn absent_incomplete_and_malformed_topology_disables_occlusion() {
        let chunks = [chunk(Vec3::new(0., 2., -10.), Some("A"))];
        assert!(InteriorVisibility::from_manifest(&Value::Null, &chunks).is_none());
        let source = manifest(true, false);
        let mut broken = source.clone();
        broken["visibility"]["complete"] = false.into();
        assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
        let mut broken = source.clone();
        broken["visibility"]["portals"]
            .as_array_mut()
            .unwrap()
            .pop();
        assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
        let mut broken = source.clone();
        broken["visibility"]["portals"][0]["normal"] = serde_json::json!([1, 1, 0]);
        assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
        let mut broken = source.clone();
        broken["visibility"]["portals"][0]["max"][1] = 0.into();
        assert!(
            InteriorVisibility::from_manifest(&broken, &chunks).is_none(),
            "line/point portals fail open"
        );
        let mut broken = source.clone();
        broken["visibility"]["portals"][0]["to"] = "missing".into();
        assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
        let mut broken = source;
        broken["visibility"]["cells"].as_array_mut().unwrap().push(
            serde_json::json!({"id":"overlap","building":"A","min":[-1,0,-11],"max":[1,4,-9]}),
        );
        assert!(InteriorVisibility::from_manifest(&broken, &chunks).is_none());
    }
}
