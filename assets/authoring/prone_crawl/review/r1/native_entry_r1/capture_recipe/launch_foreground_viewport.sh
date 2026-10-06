#!/bin/bash
set -euo pipefail
: "${DISPLAY:?A graphical Blender display is required}"
ROOT=/workspace/shared/prone-crawl-20261004
blender --factory-startup --disable-autoexec "$ROOT/author/halcyon_prone_crawl_r1.blend" -t 8 --python-exit-code 1 --python "$ROOT/render/r1/capture_viewport_animation.py" > "$ROOT/render/r1/viewport_capture.log" 2>&1
