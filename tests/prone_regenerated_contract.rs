//! Source-free provenance regression fixtures, never production motion evidence.
use serde_json::{json, Value};
use vector_range::authored_prone::{
    ProneCameraTrack, ENTRY_SECONDS, R15_CAMERA_ACTION, R15_CAMERA_FINGERPRINT,
    R15_EQUIVALENCE_CONTRACT, R15_RIG_ACTION, R15_RIG_FINGERPRINT, R15_SOURCE_SHA, REMOVAL_POLICY,
};

const GENERATED: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn descriptor() -> Value {
    let mut value: Value = serde_json::from_str(R15_EQUIVALENCE_CONTRACT).unwrap();
    value["generated_source_sha256"] = json!(GENERATED);
    value["source_equivalence_sha256"] = json!("b".repeat(64));
    value["regenerated_witness_sha256"] = json!("c".repeat(64));
    value["replay_receipt_sha256"] = json!("d".repeat(64));
    value
}

#[derive(Clone)]
struct Fixture {
    camera: Value,
    receipt: Value,
}
impl Fixture {
    fn new() -> Self {
        let rows: Vec<Value> = (0..4353)
            .map(|i| {
                let frame = 1. + i as f64 / 64.;
                let depth = ((frame - 11.) / 58.).clamp(0., 1.);
                let matrix = json!([
                    [1., 0., 0., 0.],
                    [0., 1., 0., 0.],
                    [0., 0., 1., -1.26 * depth],
                    [0., 0., 0., 1.],
                ]);
                json!({"candidate_frame": frame, "time_seconds": i as f64 / 3840.,
                    "normalized_depth_fraction": depth,
                    "camera_world": matrix, "common_world_delta": matrix})
            })
            .collect();
        let fingerprints = json!({
            R15_RIG_ACTION: R15_RIG_FINGERPRINT, R15_CAMERA_ACTION: R15_CAMERA_FINGERPRINT,
        });
        let camera = json!({
            "schema": "prone-entry-r15-camera-motion/v2", "sample_hz": 3840, "fps": 60,
            "units": "metres and radians; Blender world +Z up",
            "camera_local_axes": "+X right, +Y up, -Z forward",
            "duration_key_span_seconds": ENTRY_SECONDS,
            "candidate_sha256": GENERATED, "action_fingerprints": fingerprints,
            "source_equivalence": descriptor(),
            "initial_camera_world": [[1., 0., 0., 0.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]],
            "height_contract": {"mode": "replace_stance_height_during_clip",
                "allow_impact_overshoot": true, "source_endpoint_descent_m": 1.26,
                "runtime_target_prone_eye_height_m": 0.2794},
            "rows": rows,
        });
        let receipt = json!({
            "schema": "rust-duty-prone-camera-pair/v3", "clip_name": R15_RIG_ACTION,
            "candidate_sha256": GENERATED, "action_fingerprints": fingerprints,
            "source_equivalence": descriptor(),
            "source_rig_action": R15_RIG_ACTION, "source_camera_action": R15_CAMERA_ACTION,
            "camera_sample_hz": 3840, "common_motion_removal": REMOVAL_POLICY,
            "native_fps": [60, 1], "native_crop": [0, 68], "candidate_frame_offset": 1,
            "imported_frame_offset": 1.0, "candidate_frame_range": [1, 69],
            "canonical_rest_frame": 1, "source_fbx_sha256": "e".repeat(64),
        });
        Self { camera, receipt }
    }
    fn parse(&self) -> Result<ProneCameraTrack, String> {
        let asset = b"original synthetic source-free companion bytes";
        let camera = serde_json::to_vec(&self.camera).unwrap();
        let mut receipt = self.receipt.clone();
        receipt["asset_vra_sha256"] = json!(rust_duty_launcher::bytes_hash(asset));
        receipt["camera_sidecar_sha256"] = json!(rust_duty_launcher::bytes_hash(&camera));
        ProneCameraTrack::from_pair(
            asset,
            &camera,
            &serde_json::to_vec(&receipt).unwrap(),
            R15_RIG_ACTION,
        )
    }
    fn replace_proof(&mut self, proof: Value) {
        self.camera["source_equivalence"] = proof.clone();
        self.receipt["source_equivalence"] = proof;
    }
}

#[test]
fn regenerated_binding_preserves_actual_identity_and_validated_proof() {
    let fixture = Fixture::new();
    let binding = fixture.parse().unwrap().binding_identity();
    assert_eq!(binding["candidate_sha256"], GENERATED);
    assert_ne!(binding["candidate_sha256"], R15_SOURCE_SHA);
    assert_eq!(binding["source_equivalence"], descriptor());
    assert_eq!(
        binding["source_equivalence"]["approved_source_sha256"],
        R15_SOURCE_SHA
    );
    assert_eq!(binding["receipt_schema"], "rust-duty-prone-camera-pair/v3");
    assert_eq!(
        binding["sidecar_schema"],
        "prone-entry-r15-camera-motion/v2"
    );
}

#[test]
fn all_pinned_proof_fields_reject_missing_or_stale_values_with_repaired_file_hashes() {
    let fixture = Fixture::new();
    let contract: Value = serde_json::from_str(R15_EQUIVALENCE_CONTRACT).unwrap();
    for key in contract.as_object().unwrap().keys() {
        let mut changed = fixture.clone();
        let mut proof = descriptor();
        proof[key] = json!("unreviewed");
        changed.replace_proof(proof);
        assert!(changed.parse().is_err(), "changed pin admitted: {key}");
        let mut proof = descriptor();
        proof.as_object_mut().unwrap().remove(key);
        changed.replace_proof(proof);
        assert!(changed.parse().is_err(), "missing pin admitted: {key}");
    }
}

#[test]
fn malformed_dynamic_digests_source_mismatch_and_boolean_only_proofs_fail() {
    let fixture = Fixture::new();
    for key in [
        "source_equivalence_sha256",
        "regenerated_witness_sha256",
        "replay_receipt_sha256",
    ] {
        let mut changed = fixture.clone();
        let mut proof = descriptor();
        proof[key] = json!("A".repeat(64));
        changed.replace_proof(proof);
        assert!(changed.parse().is_err(), "malformed digest admitted: {key}");
    }
    let mut changed = fixture.clone();
    let mut proof = descriptor();
    proof["generated_source_sha256"] = json!("f".repeat(64));
    changed.replace_proof(proof);
    assert!(changed
        .parse()
        .unwrap_err()
        .contains("generated source mismatch"));
    changed.replace_proof(json!({"passed": true}));
    assert!(changed.parse().is_err());
    changed.replace_proof(Value::Null);
    assert!(changed.parse().is_err());
}

#[test]
fn receipt_and_sidecar_must_carry_the_same_proof_and_new_schema() {
    let fixture = Fixture::new();
    let mut changed = fixture.clone();
    changed.receipt["source_equivalence"]["source_equivalence_sha256"] = json!("f".repeat(64));
    assert!(changed.parse().unwrap_err().contains("receipt/sidecar"));
    let mut changed = fixture.clone();
    changed
        .receipt
        .as_object_mut()
        .unwrap()
        .remove("source_equivalence");
    assert!(changed.parse().is_err());
    let mut changed = fixture.clone();
    changed.camera["schema"] = json!("prone-entry-r15-camera-motion/v1");
    assert!(changed.parse().unwrap_err().contains("camera clock"));
    let mut changed = fixture.clone();
    changed.camera["sample_hz"] = json!(480);
    assert!(changed.parse().is_err());
    let mut changed = fixture;
    changed.receipt["native_crop"] = json!([1, 69]);
    assert!(changed.parse().is_err());
}

#[test]
fn original_v2_cannot_admit_generated_bytes_or_use_a_proof_override() {
    let mut fixture = Fixture::new();
    fixture.camera["schema"] = json!("prone-entry-r15-camera-motion/v1");
    fixture.receipt["schema"] = json!("rust-duty-prone-camera-pair/v2");
    assert!(fixture.parse().unwrap_err().contains("exact approved"));
    fixture.camera["candidate_sha256"] = json!(R15_SOURCE_SHA);
    fixture.receipt["candidate_sha256"] = json!(R15_SOURCE_SHA);
    assert!(fixture.parse().unwrap_err().contains("exact approved"));
    fixture
        .camera
        .as_object_mut()
        .unwrap()
        .remove("source_equivalence");
    fixture
        .receipt
        .as_object_mut()
        .unwrap()
        .remove("source_equivalence");
    let binding = fixture.parse().unwrap().binding_identity();
    assert_eq!(binding["candidate_sha256"], R15_SOURCE_SHA);
    assert!(binding.get("source_equivalence").is_none());
}

#[test]
fn regenerated_mode_cannot_relabel_original_or_reuse_original_witness() {
    let fixture = Fixture::new();
    let mut changed = fixture.clone();
    changed.camera["candidate_sha256"] = json!(R15_SOURCE_SHA);
    changed.receipt["candidate_sha256"] = json!(R15_SOURCE_SHA);
    let mut proof = descriptor();
    proof["generated_source_sha256"] = json!(R15_SOURCE_SHA);
    changed.replace_proof(proof);
    assert!(changed.parse().unwrap_err().contains("distinct"));
    let mut changed = fixture;
    let mut proof = descriptor();
    proof["regenerated_witness_sha256"] = proof["approved_witness_sha256"].clone();
    changed.replace_proof(proof);
    assert!(changed.parse().unwrap_err().contains("reuses"));
}
