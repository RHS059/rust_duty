# Reference measurement reproducibility

No original footage or derived screenshots are included in this numeric packet. Keep any authorized original media and generated pixel outputs local/private.

To regenerate raw tracks, install Python packages numpy, scipy, and opencv-python-headless in your analysis environment, then run measure_reference_landmarks.py with REFERENCE_MEDIA_DIR set to the directory containing the two named MP4 sources and REFERENCE_REVIEW_OUTPUT set to a local-only output directory. The measurement run used OpenCV5.0.0, NumPy2.3.5, and SciPy1.17.0.

The script decodes native frames, applies recorded point/template tracking, emits exact raw-index/PTS numerical tracks, and generates local-only annotated contact sheets for QA. It never retimes source frames. The legacy raw *_inliers fields contain normalized template correlation scaled1000; they are not inlier counts or acceptance scores, and were intentionally omitted from reference_tracks_validated.csv. The receiver in R1 forward/backward/right is consecutive optical flow; its template-correlation field is not a reliability score.

Use reference_measurement_contract.json for fixed source masks and review uncertainty. Exclude R1right muzzle[418,429) and R1left muzzle[531,549); those raw measurements remain in the diagnostics but are false in the validated usability columns. These exclusions came from reference-pixel QA, not candidate errors. The reviewer inspected all declared windows every3rd raw frame (20Hz), retaining all60Hz computed samples.

The verified numeric CSV, exact source hashes, source windows, normalization definition, and v2/v3 contracts are authoritative. Candidate reports record fixed scales, source frames, phase offsets and thresholds. Uncertainty estimates are visually assessed bounds, not statistical confidence intervals.
