#!/usr/bin/env bash
# EKF port conformance runner + fixture regeneration (Step 5 of the port plan; policies in
# ../ekf_port_contract.md). Regenerates the scenario corpus deterministically, drives the C++
# ekf_replay and the Rust examples/ekf_replay.rs on every scenario, runs the fail-closed
# comparator, and verifies (or with --freeze, rewrites) the SHA-256 fixture manifest.
#
# Prerequisites:
#   - fork built with: colcon build --packages-select autoware_ekf_localizer \
#       --cmake-args -DCMAKE_BUILD_TYPE=Release -DEKF_BUILD_REPLAY=ON
#   - realtime_core: cargo build --release -p realtime_ekf_localizer --examples
#
# Usage: run_conformance.sh [workdir] [--freeze]
# (no -u: ROS setup.bash reads unset COLCON_* variables)
set -eo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WS=/autoware_workspace
RT=$WS/realtime_core
WORK="${1:-/tmp/ekf_conformance}"
FREEZE="${2:-}"

mkdir -p "$WORK/scenarios" "$WORK/traces"

# 1. Regenerate the deterministic scenario corpus.
(cd "$RT" && cargo build --release -p realtime_ekf_localizer --examples >/dev/null)
"$RT/target/release/examples/gen_scenarios" "$WORK/scenarios" >/dev/null
python3 "$HERE/gen_realdata_scenario.py" --duration 60 \
  --out "$WORK/scenarios/realdata.scn" >/dev/null

# 2. Verify the frozen scenario manifest (or refreeze with --freeze).
(cd "$WORK/scenarios" && sha256sum *.scn) > "$WORK/scenarios.sha256"
if [ "$FREEZE" = "--freeze" ]; then
  cp "$WORK/scenarios.sha256" "$HERE/fixtures/scenarios.sha256"
else
  diff -u "$HERE/fixtures/scenarios.sha256" "$WORK/scenarios.sha256" \
    || { echo "scenario manifest drift (regen is not deterministic?)"; exit 1; }
fi

# 3. Differential run: C++ vs Rust on every scenario, fail-closed comparison.
# shellcheck disable=SC1091
source "$WS/install/setup.bash"
CPP_BIN=$WS/install/autoware_ekf_localizer/lib/autoware_ekf_localizer/ekf_replay
RUST_BIN=$RT/target/release/examples/ekf_replay

python3 "$HERE/compare_traces.py" --self-test

fail=0
for scn in "$WORK"/scenarios/*.scn; do
  name=$(basename "$scn" .scn)
  AUTOWARE_EKF_POSE_TRACE="$WORK/traces/${name}_cpp.csv" "$CPP_BIN" "$scn" 2>/dev/null
  "$RUST_BIN" "$scn" "$WORK/traces/${name}_rust.csv"
  echo "--- $name"
  python3 "$HERE/compare_traces.py" \
    "$WORK/traces/${name}_cpp.csv" "$WORK/traces/${name}_rust.csv" || fail=1
done

# 4. Verify (or refreeze) the expected-trace manifest: the C++ traces are the oracle.
(cd "$WORK/traces" && sha256sum *_cpp.csv) > "$WORK/traces.sha256"
if [ "$FREEZE" = "--freeze" ]; then
  cp "$WORK/traces.sha256" "$HERE/fixtures/expected_cpp_traces.sha256"
  echo "frozen: fixtures/scenarios.sha256 fixtures/expected_cpp_traces.sha256"
else
  diff -u "$HERE/fixtures/expected_cpp_traces.sha256" "$WORK/traces.sha256" \
    || { echo "C++ oracle traces drifted from the frozen manifest"; exit 1; }
fi

exit $fail
