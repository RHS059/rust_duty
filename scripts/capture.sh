#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
./target/release/vector-range --capture --output=docs/screenshots/range.png
./target/release/vector-range --capture-ads --output=docs/screenshots/ads.png
./target/release/vector-range --capture-fixtures --output=docs/screenshots/fixtures.png
