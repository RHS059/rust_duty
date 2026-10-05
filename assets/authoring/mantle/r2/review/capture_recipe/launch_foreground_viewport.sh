#!/bin/bash
set -euo pipefail
: "${DISPLAY:?A graphical Blender display is required}"
ROOT=/workspace/shared/vault-review-20261005
blender --factory-startup --disable-autoexec "$ROOT/recovery/candidate/aella_mantle_r2.blend" -t 8 --python-exit-code 1 --python "$ROOT/render/capture_viewport_animation.py" > "$ROOT/render/viewport_capture.log" 2>&1
