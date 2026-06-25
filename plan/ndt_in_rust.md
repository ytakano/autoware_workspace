# Porting `autoware_ndt_scan_matcher` to Rust — Roadmap

## Goal (set 2026-06-25)

**Full Rust port of the package, NDT engine included.** End state: C++ is only the rclcpp I/O shell
(Node, sub/pub, tf2, agnocast, message types); Rust holds the **NDT engine + node orchestration +
state**. Decisions:

1. **Rust owns the plain-data node state**; C++ callbacks are thin dispatchers that only call Rust
   over FFI.
2. **Rust-ize everything, including the NDT engine** (`multigrid_ndt_omp` → Rust: point cloud,
   voxel-grid covariance, kdtree, align, More-Thuente line search, covariance — replacing PCL + Eigen).
3. **Core logic stays `no_std`-capable** so the **final artifact is reusable on awkernel** (a design
   requirement). Build the ROS node first with **std + rayon**; the awkernel async/no_std backend
   comes later.
4. **ENGINE-FIRST:** the #1 immediate goal is the ROS 2 NDT engine itself, *then* the node logic.

awkernel (TIER IV's no_std async Rust kernel) is a **low-priority** secondary target: its
constraints must not gate progress, but the `no_std`-capability and `ParReduce` seam keep it open.

## Current state (done)

- **Scaffold:** crate `autoware_ndt_scan_matcher_rs/` built via **Corrosion** and linked over a C
  ABI; `cargo test` registered as a CTest; `./test.sh` runs C++ + Rust + FFI tests. `rust-hardening`
  lint gates on; clippy-clean.
- **Build switch `NDT_USE_RUST`** (CMake option): OFF = original C++ (byte-identical), ON = Rust via
  `_rs.cpp` twins. The unchanged gtests run in both as the differential oracle.
- **Pure helpers ported:** `count_oscillation`, `rotate_covariance` (zero-copy: `count_oscillation`
  reads `&[geometry_msgs__msg__Pose]` via a **bindgen** `#[repr(C)]` binding, layout-verified).
- **`no_std`-capable:** `#![cfg_attr(not(any(test, feature = "std")), no_std)]` + `libm`;
  `default=["std"]`, `ros` feature independent of `std`. Builds as rlib for `x86_64`/`aarch64-unknown-none`.
- **Coverage:** `./coverage.sh` (cargo-llvm-cov) ~97% lines / 99% functions — FFI shims + map methods
  covered by Rust direct-call tests (see "Test coverage policy").
- **Engine E1 + covariance helpers (DONE):** `nalgebra` (no_std + `libm`) math stack stood up
  (verified to compile no_std on x86_64/aarch64-unknown-none); the 6 pure `estimate_covariance`
  helpers (`calc_weight_vec`, `calculate_weighted_mean_and_cov`, Laplace, `rotate_to_*`,
  `adjust_diagonal`) ported into a Rust `covariance` module, swapped behind `NDT_USE_RUST` via the
  extracted `estimate_covariance_math{,_rs}.cpp` twin. `test_estimate_covariance` green OFF and ON.
- **Engine E2 — single voxel-grid covariance (DONE):** Rust `voxel_grid` module (voxelization +
  per-voxel mean / single-pass covariance / 3×3 symmetric-eigendecomposition eigenvalue
  regularization / inverse covariance), opaque-handle C ABI (`build`/`leaf_at`/`free`). Introduced
  `alloc` and nalgebra `symmetric_eigen` (no_std-verified). New differential gtest `test_voxel_grid`
  matches the C++ grid (via `radiusSearch`); it caught the C++ `Leaf` Identity-init quirk
  (`cov = sample_cov + I/(n-1)`), replicated for equivalence.
- **Engine E2b + E3 — multi-grid map + kd-tree (DONE):** hand-rolled no_std 3-D kd-tree
  (`kdtree.rs`, property-tested vs brute force) + `VoxelGridMap` (id-keyed `add`/`remove_target`,
  `create_kdtree`, `radius_search`) with an opaque-handle C ABI. `test_voxel_grid` extended: the
  Rust map and the C++ `MultiVoxelGridCovariance` (add 3 clouds, remove 1) return the same
  `radiusSearch` leaves (count + mean + inverse covariance). The target-map side is now complete.

Branches: scaffold/helpers/no_std on `ndt_in_rust_phase1`; engine work on `ndt_in_rust_engine` (off phase1).

## Target architecture (end state)

| Stays C++ (rclcpp I/O shell) | Becomes Rust |
|---|---|
| `rclcpp::Node`, subscriptions/publishers, services, timers | Each callback's body, orchestration, sequencing |
| tf2 buffer/listener, agnocast wrapper | Node logic **state** (pose buffers, flags, `HyperParameters`, latest EKF pos) — Rust-owned, `Mutex`-guarded (MultiThreadedExecutor) |
| ROS message types (cross via bindgen `#[repr(C)]`, zero-copy) | **NDT engine** (voxel grid, kdtree, align, line search, covariance) — replaces PCL + Eigen + `multigrid_ndt_omp` |

C++ callbacks shrink to: decompose msg / pass handles → call Rust → (Rust calls back for ROS I/O it
can't do). Engine swap is done behind the NDT interface (below), so node logic is untouched by it.

## Phase E — NDT engine (PRIMARY, engine-first)

The engine has a **narrow, well-defined interface** the node uses:
`setInputTarget`/`addTarget`/`removeTarget`/`createVoxelKdtree`, `setInputSource`, `align(guess)→NdtResult`,
`getResult`/`getHessian`/`getFinalNumIteration`, `setRegularizationPose`,
`calculateNearestVoxelTransformationLikelihood`. Swap **C++ → Rust behind this interface** via a C ABI
+ a thin C++ adapter (matching the methods the node calls) under `NDT_USE_RUST` — **no node-logic
changes** required initially.

Bottom-up steps (all `no_std`-capable; std+rayon for the node now):
- **E1 — math foundation (DONE):** `nalgebra` (no_std + `libm`); `extern crate alloc` added at E2.
- **E2 — voxel-grid covariance (single grid: DONE):** voxelize + per-voxel mean/covariance/
  eigenvalue-regularized inverse covariance; opaque-handle C ABI; differential gtest vs the C++ grid.
- **E2b + E3 — multi-grid map + kd-tree (DONE):** `VoxelGridMap` (id-keyed add/remove, centroid
  flattening, `create_kdtree`) + hand-rolled no_std 3-D kd-tree `radius_search` (replaces
  `KdTreeFLANN`). Differential gtest vs the C++ grid (add/remove + `radiusSearch`). **Target-map side complete.**
- **E4 — align + line search** (`multigrid_ndt_omp_impl` core): score/gradient/hessian + the
  optimization loop. Built bottom-up:
  - **E4a + E4b (DONE):** pure math kernels — `transform.rs` (euler↔matrix, `transform_point`,
    `gauss_constants`) and `derivatives.rs` (`compute_angle_derivatives`, `compute_point_derivatives`,
    `update_derivatives`). Verified by finite-difference oracles (gradient + translation Hessian rows
    are exact). **The pcl NDT Hessian is approximate** (its `h_ang` angle-second-derivatives deviate
    from exact, e.g. row 6 `+sy` vs exact `−sy`); we replicate pcl verbatim, so the **angle-angle
    Hessian block is validated against the C++ `NdtResult.hessian` at E4d, not by FD**. See
    [[ndt-pcl-hessian-quirk]]. `f64`, `no_std`, no FFI (C++ counterparts are private). **← NEXT (E4c)**
  - **E4c:** `compute_derivatives` — source-point loop over the map's `radius_search`/`leaf`, the
    regularization term, the score-only + nearest-voxel-likelihood loops. Serial.
  - **E4d:** `align`/`compute_transformation` — SVD solve, the default-path step (clamp + single
    eval; `use_line_search=false`), SE3 update, convergence, `NdtResult`. Adds the C++↔Rust
    differential gtest (compare `NdtResult` within tolerance; `transformation_array` +
    `transform_probability_array` give a per-iteration trace with no C++ modification).
  - **E4e / E4f:** `ParReduce` (serial + rayon, serial==rayon bit-for-bit); full More-Thuente behind
    `use_line_search`.
- **E5 — covariance module (pure helpers DONE; estimation pending):** the 6 pure
  `estimate_covariance` helpers are ported (gtest-verified). Remaining: `propose_poses_to_search`
  (variable-length `Vec<Matrix4f>` output) and the multi-NDT estimation (`estimate_xy_covariance_by_multi_ndt[_score]`,
  need the engine) — fold in once E4 exists.
- **E6 — C ABI + C++ adapter + node swap:** expose the NDT interface; swap behind `NDT_USE_RUST`;
  verify with the node integration tests (`standard_sequence_*`) OFF vs ON.

**Next:** E4c — `compute_derivatives` (the source-point loop over the map's `radius_search`,
consuming the E4a/E4b kernels), then E4d (the optimization loop + the C++ differential trace).
This is the hardest step; `ParReduce` parallelism lands at E4e (serial first).

## Phase N — node port (after the engine)

Move each callback's body into Rust (decision 1): Rust owns the plain-data state; the C++ callback
is a thin FFI dispatcher. Sequence by difficulty: `callback_initial_pose_main` (PCL-free) →
regularization / services / timer → `callback_sensor_points_main` (now calls the **Rust** engine
directly). C++ provides a small "host interface" (vtable + opaque handles) for the ROS I/O Rust
can't do (tf2 lookups, publishers, params, time). Reuses the ported helpers and the Rust engine.
End state: only the rclcpp shell is C++.

## Engine design details

- **no_std:** crate already `no_std`-capable; engine math via `nalgebra`(no_std+`libm`). `alloc`
  added at E2 (heap-backed voxel grid / kdtree / point buffers).
- **Parallelism — `ParReduce` trait**, backends selected by feature:
  - **now:** `serial` / `rayon` (host, **synchronous** — no async coloring needed for the ROS node).
  - **later (awkernel):** an `async` task-fan-out backend; that's when `align()` gains an async
    variant. Keep the per-point math in plain sync fns so adding the async boundary later is cheap.
  - **Deterministic ordered reduction** (fixed chunk count + binary-tree combine) so parallel ==
    serial bit-for-bit (matters for differential testing and certification).
- **awkernel backend (deferred) constraints** (confirmed with the user, kept for when it's built):
  no_std **+ alloc**; async/await tasks, **no threads**; task spawn needs **`'static + Send`** futures
  → share read-only data via `Arc<TargetMap: Send+Sync>` / `Arc<[Point]>`, each job a `Send+'static`
  sync closure capturing Arc clones + owned `Range` + `Copy` pose, returning a small POD partial;
  targets x86_64 + AArch64; f64 usable in task context; pure-Rust deps (no inline asm).

### Engine module breakdown (C++ → Rust)
| Rust module | Replaces (C++) |
|---|---|
| `math` | Eigen Core/Dense/Cholesky/Geometry (→ nalgebra + libm), SE3/angle-derivative helpers |
| `point_cloud` | `pcl::PointCloud<PointXYZ>`, `transformPointCloud` |
| `voxel_grid` | `multi_voxel_grid_covariance_omp` + `pcl::VoxelGridCovariance` (id-keyed add/remove) |
| `kdtree` | `pcl::KdTreeFLANN` |
| `line_search` | `unsupported/Eigen/NonLinearOptimization` (More-Thuente) |
| `ndt` | `multigrid_ndt_omp_impl.hpp` core: targets/source, `align`, score/gradient/hessian |
| `params` / `result` | `ndt_struct.hpp` (`NdtParams`, `NdtResult`) + a non-panicking `Error` |
| `parallel` | the 5 `#pragma omp` loops (the `ParReduce` abstraction) |
| `covariance` | `estimate_covariance.*` (Laplace, multi-NDT, the pure helpers) |

## FFI boundary

- **Value types / POD cross** (`rust-c-ffi-safety`): poses, covariance (`[f64;36]`), scalars,
  `#[repr(C)]` param structs, point clouds as `len + *const f32` (C++ keeps ownership), and **rosidl
  message structs by pointer** (bindgen `#[repr(C)]`, zero-copy).
- **rosidl structs via bindgen** (`use_core()`, `--target=$HOST`, layout tests + C++ `static_assert`),
  behind the `ros` feature (independent of `std`; no_std-usable). awkernel would **vendor** the
  generated bindings (bindgen needs libclang + ROS headers, absent there).
- **Build switch (方式2):** `NDT_USE_RUST` selects `_rs.cpp` twins; original C++ untouched where a TU
  is purely portable. For mixed TUs (`estimate_covariance.cpp` has NDT-dependent fns;
  `ndt_scan_matcher_core.cpp` is the big node file), first extract the portable part into its own TU.

## Verification strategy

- **Differential oracle per layer:** unit gtests (helpers, covariance); **property tests** for
  `voxel_grid`/`kdtree` vs brute force; **iteration trace diff** for `align` vs the C++ engine
  (trace-state-machine-port-verification); **`standard_sequence_*` integration tests** for the engine
  swap and the node port, run **OFF vs ON** (`NDT_USE_RUST`) — results must match.
- **Determinism:** serial ↔ rayon bit-identical via the ordered reduction; C++ ↔ Rust within tolerance.
- **no_std gate:** `cargo rustc --no-default-features --lib --target {x86_64,aarch64}-unknown-none --crate-type rlib`.
- **Coverage:** `./coverage.sh`. **Perf:** benchmark Rust align vs C++ OMP (NDT is real-time ~10 Hz).
- **Run:** `./test.sh --packages-select autoware_ndt_scan_matcher [--ctest-args -R <regex>]`.

### Test coverage policy

Follow the **`rust-coverage-meaningful-tests`** skill. Coverage is a **diagnostic map, not a target** —
the goal is that high-risk code (unsafe/FFI, public API, boundaries, error paths) is checked by tests
that would *fail for a plausible bug*. Never add a test that only calls a function to raise the
percentage; every test must have an oracle (assertion, invariant, round-trip, reference-model, or
null/edge contract).

Each port step keeps coverage meaningful as follows:
- **Pure logic** (`helper`, `covariance` pure fns, `voxel_grid::build`/`compute_icov`, `kdtree`) →
  unit + property tests with oracles (e.g. LCG-driven brute-force model for `kdtree`/`VoxelGridMap`).
- **`extern "C"` FFI shims** → **Rust direct-call tests** that (a) assert the shim equals the
  already-tested pure fn on the same input (catches wrong length / row-col order / truncation) and
  (b) assert the null/edge contract (null → documented no-op/`false`/`0` with **no write** to outputs;
  `cap`/`max_nn` truncation). This is required because **`cargo llvm-cov` sees only Rust tests** — the
  shims are *also* exercised by the C++ differential gtests, but those paths are invisible to llvm-cov.
  Do **not** chase the C++-only paths by weakening Rust tests; add Rust tests that independently assert
  the same behavior, or explicitly note the gap.
- **Cross-language behavior** → the C++ differential gtest (OFF vs ON), the authoritative oracle.
- **Unsafe FFI** → validate under **Miri**: `cargo +nightly miri test --features libm/force-soft-floats`
  (the soft-float flag is required — `libm`'s default `sqrtsd` inline asm is unsupported by Miri).
  Heavy LCG/eigen property tests are `#[cfg_attr(miri, ignore)]` to keep the UB run fast. As of E3 the
  FFI shims, the `VoxelGrid`/`VoxelGridMap` Box opaque-handle round-trips, `from_raw_parts`, and the
  out-pointer writes pass Miri with no UB.

Anti-patterns to reject: `assert!(true)`, assert-free "it runs" tests, asserting unstable debug
strings, overfitting to the current implementation, or accepting higher coverage when deleting the
key assertion would still let the test pass.

## Upstream bug / divergence discovery (process)

Porting diffs the C++ and Rust implementations directly, so it is the best opportunity to find
**upstream bugs**. When a divergence between the C++ reference and the mathematically/expected-correct
behavior is found during the port:

1. **Always notify the user immediately** — surface what / where / evidence / impact in the session.
   Never silently absorb a divergence.
2. **Record it in `porting_notes/ndt_in_rust.md`** — one entry per finding, using that file's schema
   (location · type · evidence · correct value · impact · decision · revisit trigger · upstream ·
   verification).
3. **Reproduce, don't fix locally** — the differential test vs C++ is the oracle, so the port keeps
   the C++ behavior verbatim. Mark the deviation site in-code (`PORT-QUIRK`) and pin it with a test so
   an accidental "fix" fails loudly.
4. **Fix upstream** — the correct fix belongs in pcl/Autoware; file/draft an upstream issue with the
   proof and link it from the ledger. Re-sync the port only after upstream merges.

Current findings (incl. the NDT `h_ang` "d1" sign bug): see `porting_notes/ndt_in_rust.md`.

## Skills
`rust-hardening` (all Rust), `rust-c-ffi-safety` (FFI boundary), `trace-state-machine-port-verification`
(engine align equivalence).

## Open decisions / risks
- The align core + voxel/kdtree reimplementation (~3000 lines + PCL replacement) is the bulk and the
  main risk; verify bottom-up (property tests → trace diff) and keep the C++ engine as the oracle/rollback.
- `nalgebra` no_std+libm feature set + the staticlib panic-handler nuance (rlib for awkernel; std for the node).
- Real-time performance parity with the C++ OpenMP engine.
- SIMD (x86_64/AArch64) deferred until after numeric parity; re-verify traces when added.
