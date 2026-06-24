# Porting `autoware_ndt_scan_matcher` to Rust — Roadmap

## Context & goal

We are porting `src/core/autoware_core/localization/autoware_ndt_scan_matcher` (a C++ ROS 2
`ament_cmake` package) to Rust. There are two drivers:

1. **Near-term:** move logic into memory-safe Rust incrementally without destabilizing the running
   ROS 2 node.
2. **Strategic:** make the NDT engine runnable on **tier4/awkernel** (TIER IV's `no_std` async Rust
   kernel), so the same Rust code can eventually run both in the ROS node and on awkernel.

Work happens on the `autoware_core` git branch **`ndt_in_rust`**. A scaffold is already in place
(see "Current state").

## Current state (done)

- Stub crate `autoware_ndt_scan_matcher_rs/` nested in the package, built via **Corrosion**
  (FetchContent) and linked into the C++ ament library.
- C++ → Rust C-ABI call proven end-to-end (`autoware_ndt_scan_matcher_rs_add` ← `rs_ffi_mock.cpp`
  → gtest `test_rs_ffi`).
- `cargo test` registered as a CTest (`autoware_ndt_scan_matcher_rs_cargo_test`); `./test.sh`
  runs the C++, Rust, and FFI tests together.
- Crate is `crate-type = ["staticlib", "rlib"]`, clippy-clean, `rust-hardening`-compliant.

## Architecture: what ports, what stays

| Layer | Examples | Disposition |
|---|---|---|
| ROS I/O | `rclcpp::Node`, sub/pub, services, timers, tf2, agnocast wrapper | Stay in C++ (node shell) |
| Heavy numeric kernel | `multigrid_ndt_omp` (PCL + Eigen + OpenMP + SSE) | C++ now; **ported to Rust in Track B** |
| PCL data | `pcl::PointCloud<PointXYZ>`, transforms | C++; do **not** pass ownership across FFI |
| Orchestration / decision logic | bodies of `callback_*_main`, pose gating, convergence checks | **Port to Rust (Track A)** |
| Pure numeric leaves | `rotate_covariance`, `count_oscillation`, parts of `estimate_covariance` | **Port first** (already unit-tested) |

## Two tracks

**Track A — strangler-fig (ROS node, near-term).** Keep the C++ node shell and the C++ NDT engine;
move each ROS 2 callback's orchestration/decision logic into Rust one piece at a time. C++ callbacks
shrink to thin adapters: decompose ROS msg → call Rust → publish. Existing gtests act as regression
oracle.

**Track B — awkernel NDT engine (large).** Port the NDT engine itself (`multigrid_ndt_omp`) to a
portable `no_std + alloc` Rust crate so it runs on awkernel. ~3000 lines of templated numeric C++
plus reimplementing PCL's voxel grid and kd-tree.

**Convergence point.** Once the Track B engine matures, it replaces the C++ NDT in the ROS node too,
so a single Rust engine crate serves both the ROS node (via FFI) and awkernel (native).

## FFI boundary design (Track A)

Only value types cross the boundary (`rust-c-ffi-safety`):
- **May cross:** poses (`[f64;7]` or 4×4 `[f64;16]`), covariance (`[f64;36]`), scalars, a
  `#[repr(C)]`-flattened parameter struct, point clouds as `len + *const f32` (C++ keeps ownership).
- **Must not cross:** `pcl::PointCloud`, the NDT object, Eigen types, ROS messages, `shared_ptr`.
- Start with a hand-written header; move to cbindgen when the surface grows.

## awkernel constraints → engine crate design (Track B)

Confirmed awkernel constraints: `no_std` **with** `alloc` (allocator present); concurrency is
**async/await tasks, no threads**; targets **x86_64 and AArch64** (RISC-V later); **f64 FP usable**
in task context; strict pure-Rust deps (no inline asm). Task spawn requires **`'static + Send`**
futures (no scoped concurrency).

Resulting design (locked):
- Crate is `#![no_std]` + `extern crate alloc`. Linear algebra via **`nalgebra`** (no_std + `libm`);
  transcendental math via **`libm`**. PCL voxel-grid/kd-tree reimplemented in Rust. Eigen's
  `NonLinearOptimization` (More-Thuente line search) hand-ported.
- **Parallelism** behind a `ParReduce` trait, backends `serial` / `rayon` (host) / `awkernel`:
  ```rust
  pub trait ParReduce {
      async fn reduce<A, J>(&self, jobs: alloc::vec::Vec<J>, combine: impl Fn(A, A) -> A) -> A
      where A: Send + 'static, J: FnOnce() -> A + Send + 'static;
  }
  ```
  - awkernel: spawn `async move { job() }` per chunk, join, combine.
  - rayon: `into_par_iter().map(|j| j())`. serial: run in order.
- **Ownership (to satisfy `'static + Send`):** share read-only data (`Arc<TargetMap: Send+Sync>`,
  `Arc<[Point]>`); each job is a `Send + 'static` *synchronous* closure capturing Arc clones + an
  owned `Range<usize>` + a `Copy` pose, transforms its own chunk, returns a small POD partial
  (gradient/hessian/score). Engine's mutable state stays on the orchestrator; jobs are pure.
- **Determinism:** fixed chunk count + ordered (binary-tree) reduction so parallel == serial
  bit-for-bit (matters for certification and differential testing).
- **Async coloring:** `align()` is `async fn`; only the reduce boundary awaits, per-point math stays
  sync. Expose `align_blocking()` (minimal no_std `block_on`) for the FFI/ROS path; on awkernel the
  kernel executor drives `align()` directly.
- **Feature flags:** `default = []` (always no_std+alloc); `std` (enables `rayon` backend + test
  helpers); `awkernel` (kernel backend). Tests run `--features std`; a CI gate builds
  `--no-default-features --target x86_64-unknown-none` and `aarch64-unknown-none` to enforce no_std
  purity.

### Engine module breakdown (C++ → Rust)

| Rust module | Replaces (C++) |
|---|---|
| `math` | Eigen Core/Dense/Cholesky/Geometry (→ nalgebra + libm), SE3/angle-derivative helpers |
| `point_cloud` | `pcl::PointCloud<PointXYZ>`, `transformPointCloud` |
| `voxel_grid` | `multi_voxel_grid_covariance_omp` + `pcl::VoxelGridCovariance` (id-keyed add/remove) |
| `kdtree` | `pcl::KdTreeFLANN` (no_std kd-tree) |
| `line_search` | `unsupported/Eigen/NonLinearOptimization` (More-Thuente) |
| `ndt` | `multigrid_ndt_omp_impl.hpp` core: `set_input_target/add_target/remove_target`, `set_input_source`, `align`, score/gradient/hessian |
| `params` / `result` | `ndt_struct.hpp` (`NdtParams`, `NdtResult`) + a non-panicking `Error` |
| `parallel` | the 5 `#pragma omp` loops (the `ParReduce` abstraction) |
| `covariance` | `estimate_covariance.*` (shared with node layer) |

## Phased roadmap

- **Phase 0 — Scaffold (DONE):** Corrosion build, FFI round-trip, colcon/`test.sh` test path.
- **Phase 1 — Pure leaves (Track A):** port `count_oscillation`, `rotate_covariance`, and parts of
  `estimate_covariance`. Use the `trace-state-machine-port-verification` skill with the existing
  C++ gtests as the differential oracle. Replace the C++ helpers with FFI calls.
- **Phase 2 — Stateless decision logic (Track A):** parameter validation, pose gating
  (distance/covariance thresholds), convergence evaluation (`ConvergedParamType`),
  initial→result distance.
- **Phase 3 — Callback bodies (Track A):** start with `callback_initial_pose_main` (PCL-free),
  shrink C++ callbacks to adapters; `callback_sensor_points_main` last (point cloud / NDT / tf2 stay
  in C++, Rust owns the surrounding decisions).
- **Track B — engine crate (parallel effort, larger):**
  - **B0 — Foundation:** `math` layer compiles `no_std`; stand up the CI no_std gate
    (`x86_64-unknown-none`, `aarch64-unknown-none`).
  - **B1 — Parallel abstraction:** `ParReduce` trait + serial/rayon/awkernel backends with the
    deterministic ordered reduction.
  - **B2 — Data structures:** `voxel_grid` + `kdtree`, tested against brute force (property tests).
  - **B3 — Core align:** `ndt` + `line_search`; differential trace vs the C++ engine.
  - **B4 — Integration:** drive the engine from the ROS node via FFI; later run natively on awkernel.
- **Convergence:** replace the C++ NDT with the Rust engine in the ROS node.

**Recommended build order:** Track A Phase 1 (immediate value, low risk) can proceed alongside
Track B starting at B0 → B1 → B2 → B3.

## Verification strategy

- **Differential oracle:** instrument the C++ engine to emit an abstract per-iteration trace (pose,
  score, gradient norm, hessian, `transform_probability`, `nearest_voxel_transformation_likelihood`,
  final transform); the Rust port emits the same trace; diff with tolerance. (`trace-state-machine-
  port-verification` skill.)
- **Reuse existing gtests** (`test_estimate_covariance`, `test_ndt_scan_matcher_helper`,
  `standard_sequence_*`) as regression oracles; capture real sensor-cloud + map + initial-guess
  fixtures from recorded runs / the integration tests.
- **Sub-components:** property tests for `voxel_grid`/`kdtree` vs brute force.
- **Numeric tolerance:** serial-Rust ↔ C++ within epsilon; parallel-Rust ↔ serial-Rust bit-identical
  via the deterministic reduction.
- **Multi-arch:** identical traces on x86_64 and AArch64 (portable scalar first; per-arch SIMD added
  later and re-verified).
- **no_std purity:** CI builds the crate for bare targets with `--no-default-features`.
- **Run via:** `./test.sh --packages-select autoware_ndt_scan_matcher [--ctest-args -R <regex>]`.

## Skills

`rust-hardening` (all Rust), `rust-c-ffi-safety` (FFI boundary),
`trace-state-machine-port-verification` (every port step's equivalence).

## Open decisions / risks

- awkernel FP-in-interrupt vs task-context details (FP confirmed usable in task context).
- SIMD strategy: ship portable scalar first; revisit per-arch SIMD (x86_64/AArch64) after numeric
  parity is established.
- Corrosion fetches at configure time (network); switch to a local `SOURCE_DIR` for offline/CI.
- Track B is large; Track A delivers value independently if Track B is deferred.
