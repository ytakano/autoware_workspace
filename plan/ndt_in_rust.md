# Porting `autoware_ndt_scan_matcher` to Rust — Roadmap

## Goal

**Full Rust port of the package, NDT engine included.** End state: C++ is only the rclcpp I/O shell
(Node, sub/pub, tf2, agnocast, message types); Rust holds the **NDT engine + node orchestration +
state**. Decisions:

1. **Rust owns the plain-data node state**; C++ callbacks are thin dispatchers that only call Rust.
2. **Rust-ize everything, including the NDT engine** (`multigrid_ndt_omp` → Rust: point cloud,
   voxel-grid covariance, kdtree, align, More-Thuente line search, covariance — replacing PCL + Eigen).
3. **Core logic stays `no_std`-capable** so the final artifact is reusable on awkernel (a design
   requirement). Build the ROS node first with **std + rayon**; the awkernel async/no_std backend later.
4. **ENGINE-FIRST** was the immediate goal; the engine is now done, so the focus is the node port.

awkernel (TIER IV's no_std async Rust kernel) is a **low-priority** secondary target: its constraints
must not gate progress, but the `no_std`-capability and the `ParReduce` seam keep it open.

## Status (done)

- **Scaffold + differential build.** Crate `autoware_ndt_scan_matcher_rs/` built via **Corrosion**,
  linked over a C ABI; ROS message structs via **bindgen** (`#[repr(C)]`, layout-verified); `cargo test`
  registered as a CTest; `./test.sh` runs C++ + Rust + FFI tests. `rust-hardening` lint gates on.
  **`NDT_USE_RUST`** CMake option: OFF = original C++ (byte-identical upstream), ON = Rust — the
  unchanged gtests + the `standard_sequence_*` integration tests run in **both** as the differential
  oracle. `no_std`-capable (`#![cfg_attr(not(any(test, feature="std")), no_std)]` + `libm`); builds as
  rlib for `x86_64`/`aarch64-unknown-none`.
- **NDT engine (E1–E6) DONE.** Rust modules `voxel_grid` (voxelization + per-voxel cov + eigenvalue
  regularization), `kdtree` (no_std 3-D, property-tested), `transform`, `derivatives`, `ndt` (align loop,
  fixed-size 6×6 SVD, f32 cloud transform, `NdtResult`), `covariance` (Laplace + multi-NDT + helpers),
  `engine.rs` (persistent handle). Differential-verified vs the C++ engine at every layer (helpers,
  `test_voxel_grid`, `test_align` trace diff, covariance). **WCET-audited + 0-alloc per frame**
  (`porting_notes/ndt_wcet_audit.md`; `tests/zero_alloc.rs`); **serial ≡ rayon** bit-for-bit (the
  `ParReduce` seam). The ROS node localizes on the Rust engine, ON-vs-OFF equivalent.
- **Node function-level migration (N0–N4) DONE.** A C++ **host-interface vtable** (`NdtHost` —
  fn-pointers + opaque `ctx`) lets migrated Rust callbacks drive node state for the ROS I/O Rust can't do.
  Migrated under `NDT_USE_RUST`: `service_trigger` (N0), the convergence gate (N1), the initial-pose /
  regularization callbacks (N2), the map-update distance decision (N3), and the sensor callback's compute
  — align + oscillation + convergence (`run_align`), covariance (`estimate_pose_covariance`), RGB/score —
  plus `service_ndt_align` and `map_update` off the C++ engine (N4a–e). Each has a C++ differential gtest;
  state still lives in C++ (Rust orchestrates via the vtable).
- **案B DONE.** `NDT_USE_RUST` concentrated to the **one `ndt_backend.hpp` engine typedef** + the
  per-callback dispatch `#ifdef`s; the `_rs.cpp` twins + CMake file-swaps + the FFI mock deleted;
  `estimate_covariance` de-templatized (engine files upstream-identical).
- **Engine concurrency refactor DONE (3 slices).** `NdtEngine` is **`Sync`, `&self`-only**:
  `ArcSwap<EngineState>` (map + params + id), a **thread-local** align scratch (workspace + last), and a
  tiny `ArcSwap<Option<Regularization>>`. The giant `ndt_ptr_` mutex is **removed on the ON path** — an
  `Unguarded` holder + a `const AwNdtEngine*` handle + a one-store atomic `commit_from` map publish (the
  map-update builds on a private staging engine, then commits). OFF keeps the C++ `Guarded` +
  `secondary_ndt_ptr`/`std::swap` double-buffer. Both FFI handle rules (below) hold. A
  `tests/concurrency.rs` stress test (readers aligning while a writer commits) is clean; it compiles
  under TSan via `-Zbuild-std` (CI-only; the dev sandbox blocks TSan's ASLR step). Residual: `ArcSwap`
  reclamation can drop the superseded map on the align thread (see WCET audit; future: deferred
  reclamation).

Branches: engine + node work on `ndt_in_rust_engine`; scaffold/helpers on `ndt_in_rust_phase1`.

## Target architecture (end state)

| Stays C++ (rclcpp I/O shell) | Becomes Rust |
|---|---|
| `rclcpp::Node`, subscriptions/publishers, services, timers | Each callback's body, orchestration, sequencing |
| tf2 buffer/listener, agnocast wrapper | Node logic **state** (pose buffers, flags, `HyperParameters`, latest EKF pos) — Rust-owned |
| ROS message types (cross via bindgen `#[repr(C)]`, zero-copy) | **NDT engine** — DONE (`Sync`, `&self`-only, lock-free reads; replaces PCL + Eigen + `multigrid_ndt_omp`) |

## Roadmap — full Rust port via a `Host` trait (portability is the driver)

**Why:** the NDT scan matcher must run **outside ROS** — on bare-metal / the no_std async kernel
target — so the node logic (callbacks' bodies + state + sequencing) must live in Rust, expressed
against an **abstract port interface**, with each environment supplying its own implementation. This is
not just "tidy the ROS node"; it is "the matcher is reusable anywhere."

**Architecture — a Rust `Host` trait (decided):** the node orchestration is **no_std + alloc** Rust,
**generic over `H: Host`** (static dispatch — no `dyn`/boxing). I/O **ports are `async`**
(`MapSource::load`, output sink, clock, later tf/params/log/diagnostics); the **engine align hot path
stays sync** (WCET — called between awaits). Implementations:
- **ROS**: C++ implements the ports; a Rust **`FfiHost`** adapter wraps the existing C-ABI vtables
  (`NdtHost`/`AwDiagnostics`) as a `Host`; the sync rclcpp callbacks `block_on` the async node fns.
- **no_std async kernel**: implements the same `Host` natively (its async runtime).
- **Tokio reference** (`examples/`): a std `Host` impl with async/await + synthetic data — the
  portability + async-boundary proof, and the std stand-in for the kernel's async backend.

**Why this shape:** the remaining callbacks (`map_update`, `service_ndt_align`, `sensor_points`) are all
**ROS-I/O-heavy** — tf2 lookups, the async `pcd_loader` service, ~20 publishers, PCL — with the compute
already in Rust. So the right structure is to make that ROS I/O the **port boundary**: the Rust logic
above it is reusable; ROS/kernel/Tokio differ only below it. (Messages cross per the C-types/POD policy
in Key decisions; ROS messages are marshaled at the `FfiHost` boundary.) The full "rclcpp shell only"
end state is reached when every callback's logic is in Rust over the ports.

**Plan (foundation first, then ROS adoption, then callbacks):**
- **Slices 1–2 DONE** (the function/callback-level wins with minimal ROS I/O): `AwDiagnostics` vtable +
  `service_trigger_node`; `callback_initial_pose` + `callback_regularization_pose` fully in Rust.
- **Foundation DONE** — additive, no ROS-path change: `src/host.rs` (the `Host`/port traits —
  `MapSource` async via RPITIT, `OutputSink`, `Clock` — no_std+alloc, static dispatch) +
  `src/scan_matcher.rs` (a `no_std` async orchestration over the existing `NdtEngine`: `update_map` via
  `MapSource` → staging clone → `commit_from`; sync `match_scan`). Two reference `Host` impls on
  **synthetic** data prove standalone, no-ROS operation (both recover the known transform):
  `examples/tokio_ndt.rs` (Tokio async/await) and `examples/threads_ndt.rs` (`std::thread` + a
  hand-rolled `core::task` `block_on` — no async runtime; concurrent align + map-update on a shared
  `Arc<ScanMatcher>`, the two concurrency models a kernel might use). Verified: `cargo run --example` (×2,
  transform recovered) + clippy/fmt + the no_std rlib builds (`x86_64`/`aarch64-unknown-none`). PCD /
  recorded-scan input and the no_std-kernel `Host` impl come later.
- **Match verdict in the portable core DONE** — additive, no ROS-path change. The convergence decision
  is now `no_std` and exposed through `ScanMatcher`: new `src/convergence.rs` (`evaluate_convergence` +
  `ConvergenceInput/Verdict`, moved out of the std-gated `node`), `run_align`/`AlignOutcome` un-gated to
  no_std, `NdtEngine` stores the score-gate params (`set_convergence_params`) + `align_outcome`, and
  `MatchResult` gained `converged` + `oscillation_num`. Both examples now assert `converged`. So the
  portable matcher reports the same verdict the node gates on — the prerequisite that **unblocks ROS
  adoption** (there is now real `ScanMatcher` behaviour for an `FfiHost` to drive). Verified: examples
  (`converged=true`), `cargo test`/clippy/fmt, no_std rlib (both bare targets), and C++ ON
  (`test_convergence_verdict` + `test_node_run_align` green) / OFF.
- **Covariance in the portable core DONE** — additive, no ROS-path change. `estimate_pose_covariance`
  (FIXED_VALUE / LAPLACE / MULTI_NDT / MULTI_NDT_SCORE, the candidate re-align/score against the live
  map) is un-gated to no_std (`cov_estimate`/`covariance` were already no_std), `NdtEngine` stores the
  `CovarianceConfig` (`set_covariance_config`) + a self-contained `estimate_covariance` (derives the
  rotation from the result pose), `host::CovarianceResult` carries the 6×6, and
  `ScanMatcher::match_scan_with_covariance` returns `(MatchResult, CovarianceResult)`. tokio_ndt
  estimates by MULTI_NDT and asserts a finite, positive-diagonal covariance. So the portable matcher now
  produces the **full** sensor-match output (pose + verdict + covariance). Verified: examples, `cargo
  test`/clippy/fmt, no_std rlib (both bare targets), C++ ON (`test_estimate_pose_covariance` +
  `test_estimate_covariance_multi` green) / OFF.
- **ROS adoption (`FfiHost`) — map-update slice DONE** — the production node's map-update now runs
  through the portable `apply_map_update` (the async `MapSource` Host port). New std-gated
  `node_map_update.rs`: `AwMapSource { ctx, fill }` vtable + an `FfiHost` impl of `MapSource` (load
  builds a `MapDelta`, calls `fill`, returns a ready future) + push-builder FFIs
  (`..._map_delta_add`/`_remove` over an opaque `*mut MapDelta`) + `..._ndt_engine_update_map` which
  `block_on`s the orchestration (the C++ pcd wait is synchronous, so one poll). `apply_map_update`
  factored out of `ScanMatcher::update_map` (+ a `rebuild` mode using `NdtEngine::clone_empty`; empty
  delta → no-op). C++ `map_update_module.cpp` replaced the staging+commit sequence with one FFI call
  whose `fill` runs the existing pcd-loader and pushes the add/remove delta — no engine-ownership move,
  the sensor hot path untouched. Verified: ON build + **all 18 tests** (incl. the
  `standard_sequence` / `once_initialize_at_out_of_map` (rebuild) / `particles_num` integration tests,
  the real map-update oracle) / OFF build; Rust examples behave identically; no_std rlib both targets.
- **Sensor-match consolidation — NEXT** — route `callback_sensor_points_main` through
  `match_scan_with_covariance` (needs the portable result extended, or kept getters, for the publish
  surface: markers, score traces, multi-NDT debug poses, validity flags). Then `service_ndt_align`.
- **Port the callbacks over the ports** — `sensor_points` (highest value; align/cov/score already Rust)
  → `service_ndt_align` → `map_update` (tf/async-service/publishers become port methods). Each keeps
  the ON-vs-OFF integration tests green; the kernel `Host` stub closes the loop (no_std link of the
  node logic).

**FFI mechanism — RESOLVED:** the C-ABI + bindgen + host **vtable** stays the C↔Rust boundary (the
`FfiHost` adapter wraps it as the Rust `Host` trait); `cxx` deferred (see the prior note — its payoff is
the C++-owns-a-Rust-object direction; reconsider at the ROS-adoption step gated on a Corrosion×cxx spike).

**Verification shift:** ROS-side, the oracle is **whole-callback observable equivalence** (published
topics + diagnostics + state) via the `standard_sequence_*` / `once_initialize_*` / `particles_num_*`
integration tests, ON vs OFF; portability-side, the **no_std rlib build** + the **`tokio_ndt` /
`threads_ndt` examples** prove the node logic runs without ROS (async and thread/no-runtime models).

## Key decisions (still binding)

- **`NDT_USE_RUST` OFF = byte-identical upstream** is the differential oracle; never let ON-only changes
  alter the OFF build. Keep the C++ engine as oracle/rollback.
- **The two FFI handle rules** (implemented norm, not aspirational): (1) C++ holds only a **`const`**
  pointer to a Rust instance — every "mutating" op goes through a `&self` FFI backed by `Sync` interior
  mutability; (2) unsafe Rust forms only **`&*ptr`**, never `&mut *ptr` — so a shared `&NdtEngine` is
  sound across concurrent ROS callbacks without an external lock. See [[ndt-engine-ffi-locking]].
- **The C FFI header is cbindgen-generated** (`autoware_ndt_scan_matcher_rs/cbindgen.toml`, run by
  Corrosion's `corrosion_experimental_cbindgen`) — a single source of truth from the Rust `#[repr(C)]`
  structs / `extern "C"` fns, not hand-synced. Do **not** hand-write the C header; change the Rust FFI
  and rebuild (a stale C++ vtable mismatch then becomes a compile error, not runtime UB). Needs
  `cbindgen >= 0.29` (earlier versions skip edition-2024 `#[unsafe(no_mangle)]`).
- **ROS message types cross as rosidl C types (bindgen) or extracted POD/buffers — never C++ message
  types.** The C++ message ABI (`std::string`/`std::vector`/`shared_ptr`) is unstable and not
  bindgen-able; the rosidl **C** structs (`geometry_msgs__msg__*`, `rosidl_runtime_c__String`/`…__Sequence`)
  have stable layouts that bindgen binds directly. But rclcpp delivers **C++** messages (separate memory
  from the C type), so by message shape:
  - **forward-only** callbacks (push the message to a buffer) → pass it as an **opaque token**
    (`const void*`), never dereferenced in Rust;
  - **fixed/POD messages** (no string/sequence — `Pose`/`Point`/`Quaternion`/…) → the C and C++ layouts
    coincide, so read them **zero-copy via the bindgen C type** (as `count_oscillation` does), guarded by
    a C++ `static_assert(sizeof/offsetof)` + a Rust layout test;
  - **messages with strings/sequences** (`PoseWithCovarianceStamped`, `PointCloud2`, …) → do **not**
    reinterpret the C++ object as the C type; pass the **needed scalars + raw data buffer**
    (`const float* + len`, `(ptr, len)` strings) as plain C args;
  - **publishing** → Rust returns POD; a C++ host shim builds + publishes the C++ message (a future
    rcl/C-typesupport path could let Rust build the C message directly, deferred with the rcl-shell idea).
  The maximal end state (node shell on **rcl (C)** so all messages arrive as C types Rust binds
  natively) is deferred — the agnocast/rclcpp shell stays C++ for now.
- **`no_std`-capable core + `ParReduce` seam** (serial / rayon now, async-fan-out backend later for
  awkernel). Serial is the predictable WCET baseline; backends are bit-identical via an ordered reduction.
- **Commit conventions:** sign off every commit (`git commit -s --no-gpg-sign` — upstream DCO);
  **no `Co-Authored-By` trailer** (also fails DCO); **never write "awkernel" in a commit message** — say
  "no_std".

## Verification strategy

- **ON-vs-OFF differential** is authoritative: unit gtests (helpers, covariance), property tests
  (`voxel_grid`/`kdtree` vs brute force), align trace diff (trace-state-machine-port-verification), and
  the `standard_sequence_*` integration tests — all must match between OFF (C++) and ON (Rust).
- **Bounded WCET:** a 0-allocation-per-frame test (`tests/zero_alloc.rs`) + a worst-case frame-time
  benchmark (`examples/wcet_frame.rs`), on the serial backend; `rust-realtime-review` per engine/align
  patch and a WCET re-audit (`porting_notes/ndt_wcet_audit.md`) after engine changes.
- **no_std gate:** `cargo rustc --no-default-features --lib --target {x86_64,aarch64}-unknown-none --crate-type rlib`.
- **Unsafe FFI under Miri** (`cargo +nightly miri test`, `libm/force-soft-floats`). **Coverage** via
  `./coverage.sh` is a **diagnostic map, not a target** — every test carries an oracle (assertion /
  invariant / round-trip / reference-model / null-edge contract); `extern "C"` shims get Rust direct-call
  tests because `cargo llvm-cov` sees only Rust. (`rust-coverage-meaningful-tests`.)
- **Run:** `./test.sh --packages-select autoware_ndt_scan_matcher [--ctest-args -R <regex>]` (use
  `bash -c 'source /opt/ros/humble/setup.bash …'` + `source install/local_setup.bash` for the integration
  tests; filter the package's own results via `colcon test-result --test-result-base build/<pkg>`).

## Engine internals (implemented — reference)

The concurrency end-state ("`Sync`, `&self`-only, lock-free reads") and the WCET hardening (pre-reserved
buffers, bounded neighbor count `max_nn = MAX_NEIGHBORS = 64`, stack-only fixed-size linear algebra,
serial baseline) are **done** — see `porting_notes/ndt_wcet_audit.md` and the engine commits. The
**awkernel async backend is deferred**; its constraints (kept for when it's built): no_std **+ alloc**,
async tasks (no threads), `'static + Send` futures sharing read-only data via `Arc<TargetMap: Send+Sync>`;
x86_64 + AArch64; pure-Rust deps; heap available but **bounded WCET** required (keep allocator calls off
the hot path; prefer a direct voxel-neighbor lookup over the kd-tree's worst-case O(N) traversal).

## Upstream bug / divergence discovery (process)

Porting diffs the C++ and Rust implementations directly, so it is the best opportunity to find
**upstream bugs**. When a divergence between the C++ reference and the expected-correct behavior is found:

1. **Always notify the user immediately** — what / where / evidence / impact. Never silently absorb it.
2. **Record it in `porting_notes/ndt_in_rust.md`** — one entry per finding (location · type · evidence ·
   correct value · impact · decision · revisit trigger · upstream · verification).
3. **Reproduce, don't fix locally** — the differential test vs C++ is the oracle, so the port keeps the
   C++ behavior verbatim. Mark the site in-code (`PORT-QUIRK`) and pin it with a test so an accidental
   "fix" fails loudly.
4. **Fix upstream** — the correct fix belongs in pcl/Autoware; file/draft an upstream issue and link it.

Current findings (incl. the NDT `h_ang` "d1" sign bug, fixed upstream as PR #1217): see
`porting_notes/ndt_in_rust.md` and [[ndt-pcl-hessian-quirk]].

## Skills
- `rust-hardening` — all Rust (zero-warning/clippy; no `unwrap`/`expect`/`panic`/indexing/overflow).
- `rust-c-ffi-safety` — the C↔Rust FFI boundary (the two handle rules).
- `rust-realtime-implementation` / `rust-realtime-review` — writing / reviewing the RT hot path for
  bounded WCET (the `align` loop, `compute_derivatives`, neighbor search, `ParReduce`).
- `rust-coverage-meaningful-tests` — coverage as a diagnostic map; every test carries an oracle.
- `trace-state-machine-port-verification` — engine `align` equivalence vs C++.

## Open blockers / risks
- **FFI mechanism for callback-level Rust:** `cxx` vs extending the C-ABI host vtable — needs a
  cxx×Corrosion/ament integration spike before committing.
- **Diagnostics fidelity:** reproducing the ~54 `add_key_value` emissions (exact keys, order, values)
  from Rust through the host interface, so the ON/OFF integration diff stays equivalent.
- **Async pcd_loader service** driven from Rust (the map-update path); **tf2 lookups via the host**;
  **`SmartPoseBuffer`** port-to-Rust vs host-wrap.
- **`ArcSwap` reclamation on the align thread** (rare, low-rate map updates) — option: deferred
  reclamation off the align thread if hard-RT matters.
- **Real-vehicle dataset validation** — perf + accuracy parity vs the C++ OpenMP engine (not yet run).
- **awkernel async/no_std backend** — deferred (low priority).
