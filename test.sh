#!/usr/bin/bash
# Test runner for Autoware Core packages.
#
# Usage:
#   ./test.sh                                   # test everything built under src/core
#   ./test.sh --packages-select autoware_ndt_scan_matcher
#   ./test.sh --packages-select autoware_ndt_scan_matcher \
#             --ctest-args -R test_estimate_covariance      # single ctest by regex
#
# Any extra arguments are forwarded verbatim to `colcon test`.

# Run from the workspace root regardless of the caller's CWD.
cd "$(dirname "$(readlink -f "$0")")"

source /opt/ros/humble/setup.bash
if [ -f install/setup.bash ]; then
  source install/setup.bash
fi

colcon test \
  --base-paths src/core \
  --return-code-on-test-failure \
  --event-handlers console_direct+ \
  "$@"
rc=$?

# Always print the per-test summary, even when tests failed above.
colcon test-result --verbose

exit "$rc"
