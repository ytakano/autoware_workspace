# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is a **development environment wrapper** for [Autoware Core](https://github.com/autowarefoundation/autoware), not the Autoware source itself. The only version-controlled content is:

- `docker/` — containerized ROS 2 Humble dev environment
- `bootstrap.sh` / `build.sh` — workspace bootstrap and build scripts
- `.claude/skills/` — Rust development/porting skills (see below)

Everything else is generated and **gitignored**: `src/` (Autoware source pulled via `vcs import`), `autoware/` (cloned meta-repo), and the colcon `build/`, `install/`, `log/` directories. Do not expect these to be tracked; they are reconstructed by the scripts below.

## Workflow

All development happens **inside the Docker container**. The host-side flow (run from `docker/`):

```sh
sh build.sh        # build the image (passes host USERNAME/UID/GID as build args)
sh up_docker.sh    # start the container (mounts repo root at /autoware_workspace)
sh exec_zsh.sh     # attach a shell; exec_zsh_root.sh for root
sh down_docker.sh  # stop
sh rebuild.sh      # rebuild image with --no-cache
```

Inside the container (run from `/autoware_workspace`, in order):

```sh
./bootstrap.sh   # clone autoware, vcs import src/ from repositories/*.repos, rosdep install
./build.sh       # colcon build --symlink-install --base-paths src/core --cmake-args -DCMAKE_BUILD_TYPE=Release
```

`bootstrap.sh` is the one-time bootstrap; `build.sh` is the iterative build. Both `source /opt/ros/humble/setup.bash`. The build only compiles `src/core` (the Core packages), not the full Universe tree.

The bootstrap script is named `bootstrap.sh` (not `setup.sh`) on purpose: the container's shell is **zsh**, and ROS's `/opt/ros/humble/setup.bash` uses `${BASH_SOURCE[0]}` to find its own directory. Under zsh that expands empty and falls back to the current directory, so a workspace-root file named `setup.sh` would get sourced and run by accident. **When sourcing the ROS/workspace environment in zsh, prefer `source /opt/ros/humble/setup.zsh` and `install/local_setup.zsh`** over the `.bash` variants.

### Running tests

`./test.sh` is the test runner. It wraps `colcon test --base-paths src/core --return-code-on-test-failure` (exits non-zero on failure) followed by `colcon test-result --verbose`, and forwards any extra arguments verbatim to `colcon test`. Run it with `bash` (its shebang) — never `source` it in zsh.

```sh
./test.sh                                          # all tests built under src/core (includes the slow integration/launch tests)
./test.sh --packages-select autoware_ndt_scan_matcher
./test.sh --packages-select autoware_ndt_scan_matcher \
          --ctest-args -R test_estimate_covariance  # single ctest by regex
```

For the `autoware_ndt_scan_matcher` Rust port, the fast math tests are `test_estimate_covariance` and `test_ndt_scan_matcher_helper`; the `standard_sequence_*` / launch tests are slow (300s timeouts, need PCD maps), so filter with `--packages-select` / `--ctest-args -R` during iteration.

### Building / testing a single package

After `bootstrap.sh` has populated `src/`, use colcon's package selection rather than rebuilding everything:

```sh
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select <pkg> --cmake-args -DCMAKE_BUILD_TYPE=Release
colcon test --packages-select <pkg>
colcon test-result --verbose
```

## Source layout (after setup)

`src/` is organized into `core/`, `universe/`, `sensor_component/`, and `launcher/`. The build targets `src/core/`, which contains the Core packages (e.g. `autoware_core`, `autoware_msgs`, `autoware_utils`, `autoware_lanelet2_extension`, `agnocast`, message definitions, and rviz plugins). Linting config (`.clang-format`, `.clang-tidy`, `.pre-commit-config.yaml`, etc.) lives in the cloned `autoware/` directory, not at the repo root.

## Rust skills — important

This environment is set up for **porting Autoware C++ components to Rust**. Three skills in `.claude/skills/` are authoritative and should be applied automatically when relevant:

- **rust-hardening** — applies to *all* Rust written here, not just "production" code. Zero-warning / zero-clippy builds; no `unwrap`/`expect`/`panic`/indexing/slicing in non-test code; explicit checked/saturating/wrapping arithmetic instead of silently-overflowing ops; no lossy `as` casts (use `TryFrom`); no `let _` discarding a `Result`; rustfmt required. Test code (`#[cfg(test)]`, `tests/`, `benches/`, `examples/`) may freely use `unwrap`/`expect`/`panic`.
- **rust-c-ffi-safety** — when Rust calls C or C calls Rust: every value/pointer/struct crossing the FFI boundary is untrusted until validated against its Rust-side binding. Enforces the 26 FFI soundness rules.
- **trace-state-machine-port-verification** — when porting C++ to Rust and you need behavior-equivalence confidence: establish a C++ baseline, design a spec-level state machine + abstract trace, instrument both sides, then prove observable equivalence via differential testing.

The Rust toolchain (rustup, `cargo-binutils`, `mdbook-mermaid`) is installed in the container image.
