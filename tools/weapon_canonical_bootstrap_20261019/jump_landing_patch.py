"""Derive the reviewed r8 landing Action in memory from the pinned r7 source.

This stdlib-only module does not import Blender, read or save a .blend file,
render, export, or access the network. The caller hashes the source file and
passes ``bpy.data.actions`` plus that hash to ``apply_patch`` before selecting
export Actions. The candidate .blend hash identifies the reviewed checkpoint;
this operation reproduces its Action record, not its whole-file bytes.
"""

import hashlib
import json


SOURCE_SHA256 = "a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b"
APPROVED_CANDIDATE_SHA256 = "db30e98a8d63cb4e9075ec2930cd5d34d385780ab374e1d6386f42d1e0fe7b3b"
SOURCE_ACTION = "jump_land_r7"
CANDIDATE_ACTION = "jump_land_r8_ease_candidate"
SOURCE_ACTION_SHA256 = "c492d72146c1d23e054599137e40c936c1bb2b2766862d858af8316f092d6bda"
CANDIDATE_ACTION_SHA256 = "6e8daff6b1e0d81780336733cc397c965d65c2a9b5eb908cbeb5346a51965d56"
ORIGINAL_ACTION_COUNT = 103
ACTION_CURVE_COUNT = 775
CURVE_PATH = 'pose.bones["righthand_prop"].rotation_euler'
CURVE_INDEX = 1

# Every value is immutable and JSON-safe, so a shallow copy cannot mutate a
# nested value and JSON round trips preserve exact equality with this record.
PATCH_PROVENANCE = {
    "schema": "rust-duty-jump-r8-in-memory-action-patch/v1",
    "source_sha256": SOURCE_SHA256,
    "approved_candidate_sha256": APPROVED_CANDIDATE_SHA256,
    "source_action": SOURCE_ACTION,
    "candidate_action": CANDIDATE_ACTION,
    "source_action_sha256": SOURCE_ACTION_SHA256,
    "candidate_action_sha256": CANDIDATE_ACTION_SHA256,
    "curve_path": CURVE_PATH,
    "curve_index": CURVE_INDEX,
    "changed_keys": "5,6",
    "original_action_count": ORIGINAL_ACTION_COUNT,
    "action_curve_count": ACTION_CURVE_COUNT,
    "derivation": "in-memory Action copy; no whole-BLEND byte reproduction",
    "review_url": "https://github.com/RHS059/rust_duty/pull/20#pullrequestreview-5511992220",
}

# (frame, before (co, left, right), approved after (co, left, right)). These are
# the exact stored float values from the reviewed two-key correction, not a
# newly solved curve or a dependence on another PR's authoring artifacts.
KEY_PATCHES = (
    (
        5.0,
        (
            (5.0, 0.047564517706632614),
            (4.666666507720947, 0.04718858748674393),
            (5.333333492279053, 0.0479404479265213),
        ),
        (
            (5.0, 0.05365120619535446),
            (4.666666507720947, 0.04917992651462555),
            (5.333333492279053, 0.058122482150793076),
        ),
    ),
    (
        6.0,
        (
            (6.0, 0.06944283097982407),
            (5.666666507720947, 0.06229608505964279),
            (6.333333492279053, 0.07658957690000534),
        ),
        (
            (6.0, 0.07077010720968246),
            (5.666666507720947, 0.06451913714408875),
            (6.333333492279053, 0.07702107727527618),
        ),
    ),
)


class PatchValidationError(ValueError):
    """The pinned source or exact reviewed Action could not be established."""


def curve_record(curve):
    """Match the complete canonical curve record used by the r8 authoring check."""
    return {
        "path": curve.data_path,
        "index": curve.array_index,
        "extrapolation": curve.extrapolation,
        "mute": curve.mute,
        "points": [
            {
                "co": list(key.co),
                "left": list(key.handle_left),
                "right": list(key.handle_right),
                "left_type": key.handle_left_type,
                "right_type": key.handle_right_type,
                "interpolation": key.interpolation,
                "easing": key.easing,
                "amplitude": key.amplitude,
                "back": key.back,
                "period": key.period,
            }
            for key in curve.keyframe_points
        ],
    }


def action_record(action):
    """Canonical ordered record; used for inspection and synthetic fixtures."""
    return [curve_record(curve) for curve in action.fcurves]


def action_sha256(action):
    """Hash the exact canonical JSON without retaining all Action records.

    The resulting bytes equal json.dumps(action_record(action),
    sort_keys=True, separators=(',', ':')).encode(). Only one curve's record
    is materialized at a time; iteration order is significant.
    """
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, curve in enumerate(action.fcurves):
        if index:
            digest.update(b",")
        digest.update(json.dumps(curve_record(curve), sort_keys=True,
                                 separators=(",", ":")).encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()


def _identity(action):
    # Blender may return another Python wrapper for the same RNA datablock.
    pointer = getattr(action, "as_pointer", None)
    return pointer() if callable(pointer) else id(action)


def _key_coordinates(key):
    return tuple(key.co), tuple(key.handle_left), tuple(key.handle_right)


def _recipe_keys(action):
    curves = [curve for curve in action.fcurves
              if curve.data_path == CURVE_PATH and curve.array_index == CURVE_INDEX]
    if len(curves) != 1:
        raise PatchValidationError("Expected exactly one landing rotation-Y curve")
    curve = curves[0]
    keys = []
    for frame, before, after in KEY_PATCHES:
        matches = [key for key in curve.keyframe_points if key.co[0] == frame]
        if len(matches) != 1:
            raise PatchValidationError("Expected exactly one landing key at frame %g" % frame)
        if _key_coordinates(matches[0]) != before:
            raise PatchValidationError("Landing key before-record mismatch at frame %g" % frame)
        keys.append((matches[0], after))
    return curve, keys


def _apply_key_recipe(action):
    """Mutate only the approved key values and handles, after checking both."""
    curve, keys = _recipe_keys(action)
    for key, after in keys:
        key.co.y = after[0][1]
        key.handle_left = after[1]
        key.handle_right = after[2]
    curve.update()
    for key, after in keys:
        if _key_coordinates(key) != after:
            raise PatchValidationError("Updated landing key differs from approved recipe")


def _verify_originals(actions, originals, candidate):
    current = tuple(actions)
    if len(current) != len(originals) + 1:
        raise PatchValidationError("Unexpected Action count after patch")
    by_name = {action.name: action for action in current}
    expected_names = {name for name, _, _ in originals} | {CANDIDATE_ACTION}
    if len(by_name) != len(current) or set(by_name) != expected_names:
        raise PatchValidationError("Original Action names or candidate identity changed")
    if _identity(by_name[CANDIDATE_ACTION]) != _identity(candidate):
        raise PatchValidationError("Candidate Action identity changed")
    for name, identity, expected_hash in originals:
        action = by_name[name]
        if _identity(action) != identity or action_sha256(action) != expected_hash:
            raise PatchValidationError("Original Action changed: " + name)


def apply_patch(actions, source_sha256):
    """Add one exact reviewed r8 Action to a Blender-like Actions collection.

    All preflight failures occur before copying or changing an Action. On a
    failure after copying, remove only the newly derived candidate when it is
    safe to identify it. Existing Actions are never intentionally edited.
    Successful calls return a fresh, immutable-valued provenance dictionary.
    Repeated calls fail closed rather than reuse a pre-existing candidate.
    """
    if source_sha256 != SOURCE_SHA256:
        raise PatchValidationError("Pinned source SHA-256 mismatch")
    initial = tuple(actions)
    by_name = {action.name: action for action in initial}
    if CANDIDATE_ACTION in by_name:
        raise PatchValidationError("Candidate Action already exists")
    if len(initial) != ORIGINAL_ACTION_COUNT or len(by_name) != len(initial):
        raise PatchValidationError("Original Action count or unique names mismatch")
    source = by_name.get(SOURCE_ACTION)
    if source is None:
        raise PatchValidationError("Missing pinned source Action: " + SOURCE_ACTION)
    if len(source.fcurves) != ACTION_CURVE_COUNT:
        raise PatchValidationError("Source Action curve count mismatch")
    source_hash = action_sha256(source)
    if source_hash != SOURCE_ACTION_SHA256:
        raise PatchValidationError("Source full Action SHA-256 mismatch")
    _recipe_keys(source)
    originals = tuple(
        (action.name, _identity(action), source_hash if action is source else action_sha256(action))
        for action in initial
    )
    original_identities = {identity for _, identity, _ in originals}
    candidate = None
    try:
        candidate = source.copy()
        if _identity(candidate) in original_identities:
            raise PatchValidationError("Action copy reused an original datablock")
        if len(tuple(actions)) != len(initial) + 1:
            raise PatchValidationError("Action copy did not add exactly one datablock")
        if action_sha256(candidate) != SOURCE_ACTION_SHA256:
            raise PatchValidationError("Action copy does not match pinned source record")
        candidate.name = CANDIDATE_ACTION
        if candidate.name != CANDIDATE_ACTION:
            raise PatchValidationError("Candidate Action name was not accepted exactly")
        candidate.use_fake_user = True
        _apply_key_recipe(candidate)
        if len(candidate.fcurves) != ACTION_CURVE_COUNT:
            raise PatchValidationError("Candidate Action curve count mismatch")
        if action_sha256(candidate) != CANDIDATE_ACTION_SHA256:
            raise PatchValidationError("Candidate full Action SHA-256 mismatch")
        _verify_originals(actions, originals, candidate)
    except Exception as error:
        if candidate is not None and _identity(candidate) not in original_identities:
            if any(_identity(action) == _identity(candidate) for action in actions):
                try:
                    actions.remove(candidate)
                except Exception as cleanup_error:
                    raise PatchValidationError(
                        "Patch rejected (%s); derived candidate cleanup failed: %s"
                        % (error, cleanup_error)
                    ) from error
        raise
    return PATCH_PROVENANCE.copy()
