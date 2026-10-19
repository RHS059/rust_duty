# Official addon observer v4: exact Windows profile dependency successor

Preparation only. The exact source baseline is published observer-v3 at PR77
head 01e3d821d197799a342b7738b84e835b11197f24, with its original 54 regression
test methods retained and only profile-dependent expectations adapted.

Only dependency pins, the materialized context-v3 path, and the exact Windows
profile-v2 contract change in production. The profile distinguishes raw file,
raw function-slice and loaded inspect.getsource function hash domains. The
observer still compares raw installed and archive bytes only, never imports the
addon, derives acceptance from normalized bytes, modifies the original outcome,
or admits a candidate. All original filesystem, archive, identity, terminal,
resource, privacy and hash-only-report controls remain unchanged.

Synthetic fixtures now model the official Windows CRLF profile. LF-only
substitution stays visibly mismatched even if diagnostic normalization agrees.
Raw equality still does not grant native admission. CPU-only source tests do
not establish Windows execution, animation proof or successful game capture.

No public acceptance, active workflow, private assets, downloads, installations,
CI, native Blender, rendering or publication is included. The versioned package
map targets tools/onehand_windows/official-addon-observation-v4/.
