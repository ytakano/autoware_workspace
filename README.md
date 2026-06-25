# Autoware Core Development Environment

## Use Docker

First, build a docker image and attach the docker container as follows.

```
$ cd docker
$ sh build.sh
$ sh up_docker.sh
$ sh exec_zsh.sh
```

## Build Autoware Core in the Docker 

```
user@autoware %> ./bootstrap.sh
user@autoware %> ./build.sh
```

## Run Tests

`./test.sh` runs `colcon test` for the packages under `src/core` and prints a
result summary. It forwards any extra arguments to `colcon test`.

```
user@autoware %> ./test.sh                                   # all tests under src/core
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher \
                           --ctest-args -R test_estimate_covariance
```

Note: a bare `./test.sh` also runs the slow integration/launch tests
(300s timeouts, PCD maps required). Filter with `--packages-select` /
`--ctest-args -R` for quick iteration.

## Rust port (autoware_ndt_scan_matcher)

`autoware_ndt_scan_matcher` is being incrementally ported to Rust. The Rust
implementation is opt-in at build time via the `NDT_USE_RUST` CMake option;
the default build is the unchanged C++. The same gtests run in both configs as
a differential oracle (see `plan/ndt_in_rust.md` for the full design).

```
# C++ (reference) — default
user@autoware %> ./build.sh
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher

# Rust-backed (FFI) — opt in, then run the same tests
user@autoware %> colcon build --symlink-install --packages-select autoware_ndt_scan_matcher \
                   --cmake-args -DCMAKE_BUILD_TYPE=Release -DNDT_USE_RUST=ON
user@autoware %> ./test.sh --packages-select autoware_ndt_scan_matcher
```

The Rust crate lives at
`src/core/autoware_core/localization/autoware_ndt_scan_matcher/autoware_ndt_scan_matcher_rs`.
To work on it directly (fastest, no colcon):

```
user@autoware %> cd src/core/autoware_core/localization/autoware_ndt_scan_matcher/autoware_ndt_scan_matcher_rs
# `ros` feature uses bindgen over the rosidl C headers, so point it at geometry_msgs' includes.
user@autoware %> ROS_INCLUDE_DIRS=/opt/ros/humble/include/geometry_msgs \
                   cargo test --features ros   # unit + FFI + bindgen layout tests
user@autoware %> ./coverage.sh                 # test coverage (sets ROS_INCLUDE_DIRS; needs cargo-llvm-cov)
```

