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
- **Engine E4a + E4b — derivative kernels (DONE):** `transform.rs` (euler↔matrix, `transform_point`,
  `gauss_constants`) + `derivatives.rs` (`compute_angle_derivatives`, `compute_point_derivatives`,
  `update_derivatives`). Verified by **finite-difference oracles** (gradient + translation Hessian
  rows). Found the **pcl Hessian quirk** (`h_ang` "d1" `+sy` vs exact `−sy`): reproduced for C++
  parity, fixed upstream (PR #1217), see [[ndt-pcl-hessian-quirk]].
- **Engine E4c — `compute_derivatives` (DONE):** `ndt.rs` source-point loop over the map +
  regularization + the two score-only loops. Serial; reuses `AlignWorkspace` (zero steady-state
  alloc, `tests/zero_alloc.rs`). FD oracle + cross-checks.
- **Engine E4d — `align` (DONE):** the optimization loop (fixed-size 6×6 SVD, default-path step, f32
  cloud transform, convergence, `NdtResult`) + the `align` FFI shim + the **C++↔Rust differential
  gtest `test_align`** — pose / iteration_num / scores / full 6×6 Hessian / per-iteration trace match
  the C++ engine within tolerance under `NDT_USE_RUST=ON`. The NDT engine is functionally complete.
- **Engine E4e — WCET audit + hardening (DONE):** `rust-realtime-review` audit
  (`porting_notes/ndt_wcet_audit.md`) + WCET-contract docstrings, then the hardening: the hot path is
  now **zero-allocation per frame** (the 1 alloc was a `trans_cloud` over-reserve, fixed — the SVD is
  stack-only; `tests/zero_alloc.rs` asserts `align == 0`), the per-cell neighbor count is bounded
  (`max_nn = MAX_NEIGHBORS = 64`), and a frame-time benchmark exists (`examples/wcet_frame.rs`;
  baseline ≈0.43 ms mean / 0.92 ms max). The kd-tree worst-case O(N) traversal is an **accepted
  residual** (benign for physical maps).
- **Engine E4e — ParReduce (DONE):** `compute_derivatives` has a **serial** backend (zero-alloc WCET
  baseline, no_std/default) and an optional **rayon** backend (`parallel` feature, `num_threads > 1`),
  **bit-for-bit identical** (per-point contributions reduced in point-index order). Verified by exact-`==`
  serial-vs-parallel tests at both the `compute_derivatives` and `align` level; C++ differential still
  green.
- **E5 — covariance estimation (DONE)** and **E6 — node swap (DONE, E6a–d):** the persistent engine
  handle (`engine.rs`), the drop-in `NdtRustAdapter`, the node typedef swap under `NDT_USE_RUST` +
  templatized covariance, and the end-to-end run. **The ROS node localizes on the Rust NDT engine**,
  ON-vs-OFF behaviorally equivalent on the stub integration tests, C++-differential-verified at the
  function + node levels. The engine port (E2–E6) is functionally complete; remaining is Phase N +
  optional extras + real-vehicle dataset validation.

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
    [[ndt-pcl-hessian-quirk]]. `f64`, `no_std`, **allocation-free** (fixed-size nalgebra on the
    stack), no FFI (C++ counterparts are private).
  - **E4c (DONE):** `src/ndt.rs` — `compute_derivatives` (source-point loop over the map's
    `radius_search`/`leaf` + regularization) and the two score-only loops
    (`transformation_probability`, `nearest_voxel_transformation_likelihood`). Serial; reuses an
    engine-owned `AlignWorkspace` (`clear()` keeps capacity) — **amortized** zero-allocation (steady
    state; the WCET hardening — pre-reserve + direct voxel-neighbor lookup — lands at E4e), proven by
    a counting-allocator integration test (`tests/zero_alloc.rs`). Verified by a
    finite-difference oracle on the multi-point score (gradient + translation Hessian rows; a
    **pure-f64 reference score** avoids f32-cloud FD noise) + cross-checks (score-only loops ==
    `compute_derivatives`). `f64` math, `f32` clouds.
  - **E4d (DONE):** `src/ndt.rs` `align` — nalgebra **fixed-size 6×6 SVD** solve (no_std-verified,
    mirrors `JacobiSVD`), the default-path step (clamp + single eval; `use_line_search=false`), **f32
    cloud transform** (`se3_matrix_f32`/`transform_cloud_f32`, C++ `Matrix4f` parity), SE3 update,
    convergence, `NdtResult` (`AlignResult`). Plus the `align` FFI shim
    (`autoware_ndt_scan_matcher_rs_ndt_align`) and the **C++↔Rust differential gtest**
    (`test/test_align.cpp`): pose / iteration_num / scores / **full 6×6 Hessian** (incl. the
    angle-angle quirk block) / per-iteration `transformation_array` all match the C++ engine within
    tolerance (✅ passing under `NDT_USE_RUST=ON`). Rust-internal: recover-known-translation +
    identity-stays + FFI==pure marshaling test.
  - **E4e — WCET audit + hardening (DONE):** `rust-realtime-review` WCET audit
    (`porting_notes/ndt_wcet_audit.md`) + WCET-contract docstrings. Hardening: **zero-allocation per
    frame** (the 1 alloc was a `trans_cloud` over-reserve, fixed — the fixed-size 6×6 SVD is
    stack-only, probe-verified; `tests/zero_alloc.rs` asserts `align == 0`); per-cell neighbors bounded
    (`max_nn = MAX_NEIGHBORS = 64`); a frame-time benchmark (`examples/wcet_frame.rs`, baseline ≈0.43 ms
    mean / 0.92 ms max). The kd-tree worst-case O(N) traversal is an **accepted residual** (benign for
    physical maps; user-confirmed). No behavior change (differential test green).
  - **E4e — ParReduce (DONE):** `compute_derivatives` split into a **serial** backend (the
    zero-alloc, no_std/default WCET baseline) and an optional **rayon** backend (`parallel` feature,
    `NdtParams.num_threads > 1`), **bit-for-bit identical** — per-point `PointContribution`s collected
    in point-index order (rayon `IndexedParallelIterator`) and folded in that order, so enabling
    parallelism never changes output. Both backends use per-point-local grouping (the serial loop was
    restructured off interleaved-global accumulation; the slight numeric shift re-verified within the
    C++ differential tolerance). Verified by `serial_and_parallel_compute_derivatives_are_bit_identical`
    + `align_serial_equals_parallel_bit_identical` (exact `==`). Parallel is **not** the WCET baseline
    (per-frame `ws.contribs` + worker-buffer allocation + scheduling jitter). Only `compute_derivatives`
    is parallelized; the score-only loops stay serial (their score grouping was aligned). Applied
    `rust-realtime-implementation`. **← NEXT (E5 / E6)**
  - **E4e — remaining:** full More-Thuente line search behind `use_line_search` (the default path
    `use_line_search = false` is done); parallelizing the score-only loops + `computeHessian` and
    wiring `num_threads` through the C ABI are optional follow-ups (low value / deferred).
- **E5 — covariance module (DONE):** the 6 pure `estimate_covariance` helpers (gtest-verified) plus
  the engine-driving estimators in `src/cov_estimate.rs` — `propose_poses_to_search` (rotated-offset
  candidate poses), `estimate_xy_covariance_by_multi_ndt` (re-`align` per candidate → uniform weights
  → unbiased `(n-1)/n`), and `estimate_xy_covariance_by_multi_ndt_score` (transform + nearest-voxel
  score per candidate → temperature softmax). Reuses the engine (`align`, `nearest_voxel_…`) + pure
  helpers; `no_std` (control-plane `Vec` allocation). Verified by the C++ differential
  `test_estimate_covariance_multi` (propose + multi_ndt + multi_ndt_score vs `pclomp`, within
  tolerance) + Rust-side property/FFI==pure tests. `transform_cloud_by_matrix` added (and
  `transform_cloud_f32` delegates to it).
- **E6 — C ABI + C++ adapter + node swap (phased):**
  - **E6a — persistent C-ABI engine handle (DONE):** `src/engine.rs` `NdtEngine` (map + params +
    workspace + last result), **clone-able** (the node double-buffers the NDT), exposed as an opaque
    `AwNdtEngine*`: new/free/clone, set_params, set_regularization, add_target(`u64` id)/remove_target/
    create_kdtree/has_target, align→get_result, calc_transformation_probability /
    calc_nearest_voxel_likelihood, max_iterations. Reuses the engine + pure helpers; `no_std`
    (control-plane). Verified by the C++ differential `test_ndt_engine` (incremental-map handle vs C++
    `MultiGridNDT`) + Rust property/clone-independence/FFI==pure tests. `VoxelGridMap`/`VoxelGrid`/
    `KdTree`/`Node` gained `Clone`; `VoxelGridMap::is_empty` added.
  - **E6b — drop-in C++ adapter (DONE, standalone):** `include/.../ndt_rust_adapter.hpp` —
    `NdtRustAdapter` mirrors `MultiGridNormalDistributionsTransform`'s full surface over the handle
    (string `cell_id`↔`u64` map + `getCurrentMapIDs`, Rule-of-Five copy = `ndt_engine_clone`, forwards
    align/getResult/scoring/params/regularization). Ported the last method,
    `calculateNearestVoxelScoreEachPoint` (per-point score → `ndt::nearest_voxel_score_each_point` +
    FFI; `>0` ⇔ found), and added a `get_score_arrays` FFI for the per-iteration traces the node
    size-checks. `NdtEngine::set_params` now rebuilds the empty map at the new resolution (C++ applies
    leaf size at `addTarget`). Verified by the C++ differential `test_ndt_rust_adapter` (adapter vs C++
    over map mgmt / align / scoring / per-point cloud / score arrays / **copy**) + extended Rust
    FFI==pure. **The typedef swap + node build is E6c** (not done — the adapter is validated
    standalone; nothing in the node points at it yet).
  - **E6c — node typedef swap + covariance (DONE):** under `NDT_USE_RUST` the node's
    `NormalDistributionsTransform` (`ndt_scan_matcher_core.hpp`) and `NdtType`
    (`map_update_module.hpp`) alias `NdtRustAdapter` (conditional `#ifdef`, with a `PUBLIC
    NDT_USE_RUST` compile def on the node lib so the executable + sequence tests see it). The two
    covariance functions `estimate_xy_covariance_by_multi_ndt[_score]` were **templatized** over the
    NDT type (defs moved to `estimate_covariance.hpp`), so the node call sites are unchanged and
    covariance runs through the adapter → Rust engine (pure helpers already `_rs`). Verified: **OFF
    build compiles** (C++ NDT path not regressed) and **ON build compiles + links the node** (lib +
    executable) against the Rust engine; all differential tests (`test_align` / `test_voxel_grid` /
    `test_estimate_covariance{,_multi}` / `test_ndt_engine` / `test_ndt_rust_adapter`) green. The node
    now embeds the Rust NDT engine end-to-end (build-verified).
  - **E6d — end-to-end node verification (DONE):** the node's stub-driven integration tests are
    self-contained (no external PCD/rosbag — `stub_pcd_loader` serves a synthetic map, stub
    clients drive the node over real rclcpp). Ran `standard_sequence_for_initial_pose_estimation`
    (asserts the node converges to the initial pose within ±2.0), `once_initialize_at_out_of_map…`,
    `particles_num_less_than_publish_num`, and the launch test — **all pass under `NDT_USE_RUST=ON`
    (node on the Rust engine) and OFF (C++ baseline)**, plus all function-level differential tests.
    The Rust-backed node localizes correctly end-to-end, behaviorally equivalent to the C++ node on
    the stub sequence. (Real-vehicle dataset / rosbag validation is the remaining real-world step,
    outside this synthetic-test environment.)

**Next:** the engine port is functionally **complete** (E2–E6): the ROS node localizes end-to-end on
the Rust NDT engine under `NDT_USE_RUST`, ON-vs-OFF behaviorally equivalent and C++-differential-
verified at the function and node levels. Remaining is **Phase N** (callback bodies → Rust; end-state
"C++ diff = callbacks + tests only", see the Phase N section) and optional engine extras (full
More-Thuente, score-loop parallelism, FFI `num_threads`) + real-vehicle dataset validation.

## Phase N — node port (after the engine)

Move each callback's body into Rust (decision 1): Rust owns the plain-data state; the C++ callback
is a thin FFI dispatcher. Sequence by difficulty: `callback_initial_pose_main` (PCL-free) →
regularization / services / timer → `callback_sensor_points_main` (now calls the **Rust** engine
directly). C++ provides a small "host interface" (vtable + opaque handles) for the ROS I/O Rust
can't do (tf2 lookups, publishers, params, time). Reuses the ported helpers and the Rust engine.
End state: only the rclcpp shell is C++.

- **N0 — host-interface mechanism + first callback (DONE):** `src/node.rs` (std-gated) defines the
  `NdtHost` C-ABI vtable (fn pointers + opaque `ctx`) and `autoware_ndt_scan_matcher_rs_node_on_trigger`
  — the migrated body of `service_trigger_node` (set `is_activated_`; clear the pose buffer on enable),
  driving node state through the vtable. C++ provides static trampolines (`host_set_activated` /
  `host_clear_initial_pose_buffer`, `ctx == this`) and routes the callback core under `#ifdef
  NDT_USE_RUST` (keeping the diagnostics wrapper). State stays C++ (Rust orchestrates via the vtable).
  Verified: `standard_sequence_*` (which call the trigger) pass ON + OFF; `node.rs` 100% covered;
  Rust gates green; `no_std` rlib excludes `node.rs`. Establishes the pattern for N1+.
- **N1 — convergence-validation decision (DONE):** the convergence gate of `callback_sensor_points_main`
  (iteration-limit / oscillation / score-type dispatch / `is_converged`) ported to a pure
  `evaluate_convergence` + `autoware_ndt_scan_matcher_rs_node_evaluate_convergence` FFI in `node.rs`
  (no host vtable — pure scalar logic, reuses the `count_oscillation` port for `oscillation_num`).
  C++ keeps the diagnostics; under `#ifdef NDT_USE_RUST` the gate flags are computed once via the FFI
  (order-preserving), `#else` the original inline C++. **Pivoted here** from `callback_initial_pose_main`
  because that callback is thin plumbing (diagnostics + 2 gates + buffer push) with little logic worth
  porting; the convergence decision is the first slice with real, differential-testable logic and a
  concrete chunk of N3. Verified: a 108-case C++ differential gtest (`test_convergence_verdict`,
  bit-exact `EXPECT_EQ`) + Rust truth-table/FFI/null tests; `standard_sequence_*` pass ON + OFF;
  `node.rs` 100% covered; gates green; `no_std` rlib still excludes `node.rs`.
- **N2+ (remaining):** the thin callbacks `callback_initial_pose_main` / `callback_regularization_pose`
  (data path) → map-update glue → `callback_sensor_points_main` (rest) + move plain-data state into
  Rust → **N4: revert the E6 scaffolding** (adapter / typedef swap / `estimate_covariance`
  templatization / helper twins, incl. the `count_oscillation` helper-swap) to reach the
  "C++ diff = callbacks + tests only" end state. Reassess before each (Phase N is orthogonal to the
  already-met engine/awkernel goal).

**End-state diff goal (vs upstream `autoware_core` main): callbacks + tests only.** The C++ diff must
concentrate in (1) the node callback/state glue (thin Rust dispatchers + the host-interface shim) and
(2) tests — plus the one unavoidable residual: minimal `CMakeLists.txt` build glue (link the Rust lib
+ the host-interface source). This means the **E6 C++-side changes are transitional and get reverted
in Phase N**: `ndt_rust_adapter.hpp`, the `estimate_xy_covariance_by_multi_ndt[_score]`
templatization, the `NormalDistributionsTransform`/`NdtType` typedef swap, and the helper twins
(`*_helper_rs.cpp`, `estimate_covariance_math_rs.cpp`, `rs_ffi_mock.cpp`). Post-Phase-N the Rust
callbacks call `NdtEngine` + `cov_estimate` **directly** (Rust→Rust, no FFI), so the C++ engine
scaffold is unnecessary on the node path; the upstream engine files (`multigrid_ndt_omp`,
`estimate_covariance`) stay **identical to upstream** (dead on the node path, or test-only). The
remaining FFI inverts to the host interface (Rust→C++) at coarse per-callback / per-I/O granularity.

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
  targets x86_64 + AArch64; f64 usable in task context; pure-Rust deps (no inline asm). Heap **is**
  available; the constraint is **bounded WCET** — keep variable-latency allocator calls out of the
  hot path (pre-reserved buffers) and bound the neighbor search (direct voxel-neighbor lookup). See
  "Bounded WCET hot path".

### Bounded WCET hot path

The engine runs in a real-time localizer (~10 Hz) and on awkernel, where **heap is available** — so
the goal is **not** avoiding the allocator but **bounding the worst-case execution time (WCET)** of one
`align` frame. Allocator calls have variable, non-bounded latency (allocation path, fragmentation,
async lock contention), so they are kept out of the hot path; and the bar is stronger than "no alloc
in steady state": a single growth/realloc on the worst-case frame is a latency spike, so **no frame —
including the first — may allocate**. Pre-reserve buffers to worst-case capacity at setup ("hard
zero", not "amortized zero").

Per-frame bound — `T_frame ≤ max_iterations × (T_compute_derivatives + T_solve)` — bound each factor:
- **Outer loop:** hard-capped by `max_iterations` (35). ✓
- **Points P:** cap the input scan (the node voxel-downsamples it to a max).
- **Neighbors/point K:** `radius_search(max_nn = N)` — bounds collection *and* traversal (the search
  stops once `N` are found).
- **Neighbor-search traversal (the WCET weak point):** kd-tree radius search is worst-case
  `O(N_leaves)` (sparse / degenerate). For the WCET path prefer a **direct voxel-neighbor lookup**
  (compute the voxel id, fetch the ≤27 neighbor voxels from the grid index) — pcl's DIRECT7/DIRECT26
  modes — which is structurally constant-bounded (≤27 × `O(log M)` index lookups). `VoxelGridMap`
  already holds the per-grid voxel index.
- **Per-cell math + transcendentals:** fixed-size `SMatrix` ops + `libm` exp/sin/cos — bounded.
- **Solve (E4d):** fixed-size 6×6 (bounded internal iterations); never `DMatrix`.

Techniques:
- **Pre-reserved reusable buffers** (`trans_cloud`, `neighbor_idx`, per-thread accumulators): sized to
  worst case at setup, `clear()` keeps capacity → **no growth on any frame** (incl. the first).
- **Stack-only linear algebra** (`SMatrix`/`SVector`, never `DMatrix`): the flat per-point loop pops
  each frame, so **stack does not scale with cloud size**; the only depth-dependent stack is the
  kd-tree recursion, `O(log N)` via median split — make it **iterative** (explicit fixed stack) for
  the WCET path.
- **Reuse map buffers:** `create_kdtree` clears+reuses `flat_leaves`/centroid buffers.
- **Parallel backends** (rayon / awkernel async) add **scheduling jitter** — WCET analysis must
  include fan-out/join cost; the **serial** backend is the most predictable baseline. The alloc-free
  per-point math stays the parallel work unit.

E4c currently uses a reused growable `Vec` (**amortized** zero-alloc, proven by `tests/zero_alloc.rs`);
the WCET hardening (pre-reserve, `max_nn = N`, direct voxel-neighbor lookup, iterative kd-tree) lands
with E4e / the awkernel backend.

Write the RT-critical path per **`rust-realtime-implementation`**: a **WCET-contract docstring** on
each RT entry point (`align`, `compute_derivatives` — max iterations / points / neighbors-per-point;
no alloc/block/panic; only fixed-width compares; no user callbacks / logging / formatting); the
**rt-core vs control-plane** split (the runtime path is alloc-free + bounded; map build/update may
allocate); and the bounded / fixed-capacity / `Result`-on-full patterns. The crate's strict lints
(deny `unwrap`/`expect`/`panic`/`indexing_slicing`/overflow) already provide the panic-free RT lint
set, so `rust-hardening` + `rust-realtime-implementation` are complementary, not redundant.

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
- **Bounded WCET:** (a) *necessary* — an allocation-counting global allocator (`stats_alloc` / `dhat`)
  test asserts **0 allocations/deallocations per `align` frame** (incl. the first, once buffers are
  pre-reserved to worst case); (b) *the real gate* — a **worst-case frame-time benchmark** (max /
  high-percentile latency + jitter) over representative scans. Run on the serial backend (the
  predictable baseline).
- **RT review:** review every engine/align patch with **`rust-realtime-review`** (quick review); run a
  **WCET audit** (bound table + allocation/panic/loop/data-structure/Drop/async audits) on the hot
  path before any RT-readiness claim — distinguishing *static* vs *documented* vs *measured* bounds (a
  benchmark is not a proof). The **E4a–d WCET audit is done** (`porting_notes/ndt_wcet_audit.md`);
  ongoing patches get a quick review, and the audit is re-run after engine changes.
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
- `rust-hardening` — all Rust (zero-warning/clippy; no `unwrap`/`expect`/`panic`/indexing/overflow).
- `rust-c-ffi-safety` — the C↔Rust FFI boundary.
- `rust-realtime-implementation` — **writing** the RT-critical hot path (`align` loop,
  `compute_derivatives`, the per-point kernels, neighbor search, `ParReduce`): bounded /
  allocation-free / panic-free / blocking-free designs, WCET-contract docstrings, and the **rt-core**
  (runtime path) vs **control-plane** (map build/update) split.
- `rust-realtime-review` — **reviewing** engine/align patches for WCET predictability: quick review
  per patch; WCET-audit mode (bound table + allocation/panic/loop/data-structure/Drop/async audits)
  for the hot path.
- `rust-coverage-meaningful-tests` — coverage as a diagnostic map; every test carries an oracle.
- `trace-state-machine-port-verification` — engine `align` equivalence vs C++.

## Open decisions / risks
- The align core + voxel/kdtree reimplementation (~3000 lines + PCL replacement) is the bulk and the
  main risk; verify bottom-up (property tests → trace diff) and keep the C++ engine as the oracle/rollback.
- `nalgebra` no_std+libm feature set + the staticlib panic-handler nuance (rlib for awkernel; std for the node).
- Real-time performance parity with the C++ OpenMP engine.
- WCET-audit finding (`porting_notes/ndt_wcet_audit.md`): the RT path touches **no `BTreeMap`** — it
  uses the kd-tree (`Vec<Node>`) + `flat_leaves` `Vec` (O(1) `get`); the `BTreeMap`s are control-plane
  (map build) only. Open residual risks: per-cell neighbor count unbounded (`max_nn = 0`), kd-tree
  worst-case O(N) traversal, and 1 O(1) SVD allocation/frame — all addressed by the hardening slice.
- Bounded-WCET decisions: neighbor-buffer capacity `N` (cover the worst-case voxel neighborhood within
  `resolution`) + overflow policy (deterministic truncation via `max_nn = N`, **counted/logged** so a
  too-small `N` is visible — no silent cap); **direct voxel-neighbor lookup vs kd-tree** (kd-tree
  radius search is worst-case `O(N_leaves)`; direct lookup is constant-bounded — pick per WCET need);
  confirm the fixed-size 6×6 solve is bounded-time (and stack-only, not `DMatrix`) at E4d.
- SIMD (x86_64/AArch64) deferred until after numeric parity; re-verify traces when added.
