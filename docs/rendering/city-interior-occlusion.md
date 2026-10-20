# Conservative interior cell/portal visibility

Status: optional authored topology with a fail-open runtime. This is coarse
interior occlusion, not an exterior hierarchical-depth/Hi-Z implementation.

## What can be hidden

The city exporter emits one enclosed interior cell per building story. Every
window, storefront and door opening is recorded directly while its wall is
constructed; glazing is conservatively treated as an opening. Every authored
stair-floor hole connects the two adjoining story cells. Portals have padded
bounds and an axis-aligned outward normal from their `from` cell. Existing
geometry, collision, source placements and building records are preserved.

Only a record with explicit building ownership and actual bounds completely
inside one cell is assigned to that cell. Horizontal/ceiling faces use a
0.08 m inset; floor contact is permitted without crossing the floor plane. Shell, boundary,
straddling, generated-light, legacy-batch and unknown records stay unassigned
and cannot be hidden by this optimization.

At each camera:

1. Determine the camera's containing interior cell, or the exterior node.
2. Flood the portal graph, retaining crossings whose padded AABB intersects the
   camera side/far planes and whose source side faces the camera. The portal
   test omits the near plane: a ray may cross a doorway before the near clip
   and still reveal geometry beyond it. A rear-wall
   window cannot reveal a room through an opaque front wall.
3. Keep every assigned instance in a reachable cell. Normal BVH/frustum and
   explicit small-prop distance checks still apply.

This only rejects impossible straight camera rays. It does not narrow the view
cone at each portal or test intervening occluders, so many hidden objects remain
submitted. Windows and doors are always treated as open. That deliberate
conservatism avoids inventing closed doors or hiding geometry through missing
openings. Reflections, mirrors and dynamic topology are outside this model.

The camera within 0.25 m of a portal or 0.08 m of a cell boundary disables
interior rejection for that frame. This covers leaning/near-plane crossings,
door thresholds and stair transitions. Traversal uses fixed bounded stack
arrays and allocates no per-frame graph containers.

## Metadata and failure behavior

A modern level optionally carries:

```json
{
  "visibility": {
    "schema": "rust-duty-city-visibility/v1",
    "complete": true,
    "portal_count": 1,
    "cells": [{"id":"B01:0", "building":"B01", "min":[-8,0.15,-8], "max":[8,3.35,8]}],
    "portals": [{"from":"B01:0", "to":null, "min":[-1,0.15,-8.01], "max":[1,2.4,-7.99], "normal":[0,0,-1]}]
  }
}
```

Null `to` means exterior; an interior ID means another cell. Normal points from
the `from` side toward `to`/outside. A stair connection points upward from the
lower story. Portal padding is 0.05 m in the opening plane and thickness is
0.02 m. Caps are 1024 non-overlapping cells and 16384 portals.

Missing metadata, `complete: false`, malformed bounds, wrong normals, unknown
cell references, a count mismatch, an isolated cell or overlapping interiors
disable interior occlusion for the level. Loading and BVH/frustum selection
continue. The exporter sets completeness only after the entire authored
building pass has finished. A portal-count field detects a truncated list;
construction-based tests establish which openings were authored. Counts alone
are not proof of topological correctness.

The graph must be regenerated after any wall, window, door or floor-hole
change. The current runtime assumes static building topology. It does not
infer a sealed volume from collision AABBs.

## Evidence boundary

Synthetic production-parser/traversal tests cover rear-wall rejection through
a solid front wall, doors/windows on all four sides, camera-inside and boundary
cases, bidirectional stair connections, malformed/missing topology, and
unassigned shell geometry. The isolated full-city export is also structurally
validated and loaded through the real runtime. These checks do not establish
native visual acceptance or a hardware FPS improvement.

The pinned isolated fixture used for this change contains 41 cells and 617
portals: 32 doors, 48 storefronts, 512 windows and 25 stair connections. The
entire mesh binary and layout JSON remain byte-identical to the instance-only
export; original level fields are unchanged. The real runtime test examined
192 exterior viewpoints, including solid-wall portions, and rejected up to 201
already-frustum-visible interior records. Its spawn view rejected zero, as
expected for conservative open-window reachability. These are workload counts,
not timing or FPS results.
