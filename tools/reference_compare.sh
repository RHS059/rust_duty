#!/usr/bin/env bash
# Side-by-side reference/native frames at fixed comparison timestamps.
# Produces images for human first-person review only: no score is computed.
#
#   tools/reference_compare.sh REFERENCE.mp4 CAPTURE_DIR OUT_DIR REF_T:CAP_T [...]
#
# CAPTURE_DIR is a --capture-sequence output recorded with --capture-hz=60, so
# capture frame N is at N/60 s. Each REF_T:CAP_T pair (seconds) writes
# OUT_DIR/pair_<REF_T>_<CAP_T>.png: reference left, native right, both 640x360.
set -euo pipefail
if [ "$#" -lt 4 ]; then
    sed -n 2,9p "$0"
    exit 2
fi
reference=$1
capture=$2
out=$3
shift 3
mkdir -p "$out"
for pair in "$@"; do
    ref_t=${pair%%:*}
    cap_t=${pair##*:}
    frame=$(printf '%04d' "$(awk -v t="$cap_t" 'BEGIN { printf "%d", t * 60 + 0.5 }')")
    native="$capture/$frame.png"
    if [ ! -f "$native" ]; then
        echo "missing native frame $native for $pair" >&2
        exit 1
    fi
    ffmpeg -loglevel error -y -ss "$ref_t" -i "$reference" -i "$native" \
        -filter_complex "[0:v]scale=640:360[r];[1:v]scale=640:360[n];[r][n]hstack=2" \
        -frames:v 1 "$out/pair_${ref_t}_${cap_t}.png"
done
echo "wrote $# pairs to $out"
