# Repository Guidelines

## Project Structure & Module Organization

This repository is a development environment wrapper for Autoware Core. The tracked root files are the workspace scripts (`bootstrap.sh`, `build.sh`, `test.sh`), Docker environment files under `docker/`, project notes under `plan/` and `porting_notes/`, and documentation. Generated or imported trees are ignored by git: `autoware/`, `src/`, `build/`, `install/`, and `log/`.

After `./bootstrap.sh`, Autoware sources are imported into `src/`. Core packages live under `src/core/`, including `autoware_core`, `autoware_msgs`, `autoware_utils`, and related packages. The main Rust port currently lives in `src/core/autoware_core/localization/autoware_ndt_scan_matcher/autoware_ndt_scan_matcher_rs`.

## Build, Test, and Development Commands

Run normal development inside the Docker container from `/autoware_workspace`.

- `cd docker && sh build.sh`: build the ROS 2 Humble development image.
- `cd docker && sh up_docker.sh && sh exec_zsh.sh`: start and enter the container.
- `./bootstrap.sh`: clone Autoware, import repositories into `src/`, and install ROS dependencies.
- `./build.sh`: run `colcon build --symlink-install --base-paths src/core` in Release mode.
- `./test.sh`: run `colcon test` for packages under `src/core` and print verbose results.
- `./test.sh --packages-select autoware_ndt_scan_matcher`: run one package’s tests.

For direct Rust iteration, run `cargo test --features ros` from the Rust crate directory with `ROS_INCLUDE_DIRS=/opt/ros/humble/include/geometry_msgs`.

## Coding Style & Naming Conventions

Follow the upstream Autoware style for imported C++/ROS packages. Prefer package-scoped changes under `src/core/<repo>/<package>/`. Keep shell scripts POSIX-style where practical, but use the existing bash shebang when touching root scripts.

For Rust production code, keep zero-warning `clippy` and `rustfmt` output. Avoid `unwrap`, `expect`, `panic`, unchecked indexing, lossy `as` casts, and ignored `Result`s outside tests.

## Testing Guidelines

Use `./test.sh` for workspace validation. A bare run includes slow launch/integration tests, so use `--packages-select` and `--ctest-args -R <regex>` for focused iteration. Rust port work should pass both Rust tests and the corresponding C++ gtests in default and `NDT_USE_RUST=ON` builds.

## Commit & Pull Request Guidelines

Git history uses conventional prefixes such as `docs(ndt): ...`. Keep subjects imperative and scoped when useful, for example `fix(ndt): validate covariance buffer length`. Sign off commits with `git commit -s --no-gpg-sign`; upstream DCO checks require it. Do not add `Co-Authored-By` trailers. Pull requests should describe the behavior change, list test commands run, link relevant issues, and include screenshots only for UI or visualization changes.
