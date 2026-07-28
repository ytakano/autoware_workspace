#!/usr/bin/env bash
# Step-2 numeric spike regen: rebuild the C++ golden vectors from the real
# autoware_kalman_filter sources, rerun the Rust port, and report the max relative error.
# Stop condition (plan): rel > 1e-6.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKG=/autoware_workspace/src/core/autoware_core/common/autoware_kalman_filter
RT=/autoware_workspace/realtime_core
OUT="${1:-/tmp/ekf_spike}"
mkdir -p "$OUT"

g++ -O2 -DNDEBUG -I"$PKG/include" -I/usr/include/eigen3 \
  "$HERE/golden_gen.cpp" "$PKG/src/kalman_filter.cpp" "$PKG/src/time_delay_kalman_filter.cpp" \
  -o "$OUT/golden_gen"
"$OUT/golden_gen" > "$OUT/golden_cpp.csv"

(cd "$RT" && cargo run --release -p realtime_kalman_filter --example spike_golden) \
  > "$OUT/golden_rust.csv"

python3 "$HERE/compare.py" "$OUT/golden_cpp.csv" "$OUT/golden_rust.csv"
