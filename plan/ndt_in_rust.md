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

## Roadmap — callback-level Rust (the remaining phase)

The migration is currently **function-level**: C++ callback wrappers keep the ROS plumbing and call
individual Rust FFIs for sub-decisions. The end state is **callback-level**: each C++ callback is a thin
forwarder to a Rust node instance that owns the state and runs the whole body; C++ provides ROS I/O via
the host interface. Then `NDT_USE_RUST` appears only in the node `.hpp` (the member) and `.cpp` (the
forwarders) — the engine typedef/adapter and the per-callback compute `#ifdef`s disappear on the Rust
path (Rust→Rust to its own engine), reaching the **"diff vs upstream = callbacks + tests only"** goal.

Target shape:
```cpp
void NDTScanMatcher::callback_initial_pose(Msg::ConstSharedPtr msg) {
#ifdef NDT_USE_RUST
  callback_initial_pose_in_rs(ndt_scan_matcher_rs_, msg);   // Rust owns the body + state
#else
  diagnostics_initial_pose_->clear();
  callback_initial_pose_main(msg);
  diagnostics_initial_pose_->publish(msg->header.stamp);
#endif
}
```
The C++ class keeps the rclcpp entities (node, pubs/subs, tf2, timers, services) **plus** a
`NDTScanMatcherRS*` (created/destroyed in the ctor/dtor); it is **not** Rust-only — rclcpp stays C++.

**State that flips to Rust:** the engine (already Rust); `initial_pose_buffer_` /
`regularization_pose_buffer_` (`SmartPoseBuffer`, C++ `autoware_localization_util` — port to Rust or
wrap via host calls); `is_activated_`, `latest_ekf_position_`, `sensor_points_in_baselink_frame_`; the
map-update `BuilderState` / `loaded_map_`.

**Host interface scope (grows from today's 6 ops):** ~20 publishers, tf2 lookups (~85 references — tf2
is not portable, so host-only), parameters, time, logging, **the async pcd_loader service** (the
trickiest — a future-based request/wait), ~54 diagnostics `add_key_value` calls (exact key order/values
are the differential surface), and the map-update timer.

**FFI mechanism — RESOLVED: extend the C-ABI + bindgen + host vtable; `cxx` deferred.** The early
host-interface slices call **templated** C++ APIs (`DiagnosticsInterface::add_key_value<T>`,
`Publisher<MsgT>`, tf2) that `cxx` can't bind — monomorphized C++ shims are hand-written either way —
so `cxx` adds `cxx_build`×Corrosion/ament build-integration risk for little near-term gain. `cxx`'s real
payoff is the *other* direction (C++ owning a rich Rust node object): it removes the manual `Box`/`*mut`
management **and the hand-synced C header drift class**. So **reconsider `cxx` at slice 6** (the Rust
node object), gated on a small Corrosion×cxx spike. (`https://docs.rs/cxx`.)

**Incremental slices** (callback-by-callback; reuse/grow the host interface; each verified ON vs OFF):
1. **DONE** — `AwDiagnostics` host-interface vtable (the reusable diagnostics-over-host mechanism:
   clear / `add_key_value{bool,i64,f64,str}` / `update_level_and_message` / publish) + `service_trigger_node`
   fully in Rust (`autoware_ndt_scan_matcher_rs_node_on_trigger` owns the whole body).
2. **DONE** — `callback_initial_pose` + `callback_regularization_pose` fully in Rust: the diagnostics
   (clear / topic_time_stamp / is_activated / is_expected_frame_id / WARN-ERROR / publish) moved into the
   `on_initial_pose` / `on_regularization_pose` FFIs; the C++ wrappers are thin `#ifdef` forwarders and
   `callback_initial_pose_main` is `#ifndef NDT_USE_RUST` (OFF baseline only).
3. **NEXT** — `callback_timer` / `map_update`: the async `pcd_loader` service is the hard part (host ops
   to issue + poll the future). 4. `service_ndt_align`. 5. the heavy `callback_sensor_points` (tf2 + align
   + cov + ~20 publishers). Not big-bang.

**Verification shift:** the differential oracle moves from per-function bit-exact gtests to
**whole-callback observable equivalence** — published topics + diagnostics + state transitions — via the
`standard_sequence_*` / `once_initialize_at_out_of_map_*` / `particles_num_*` integration tests, ON vs OFF.

## Key decisions (still binding)

- **`NDT_USE_RUST` OFF = byte-identical upstream** is the differential oracle; never let ON-only changes
  alter the OFF build. Keep the C++ engine as oracle/rollback.
- **The two FFI handle rules** (implemented norm, not aspirational): (1) C++ holds only a **`const`**
  pointer to a Rust instance — every "mutating" op goes through a `&self` FFI backed by `Sync` interior
  mutability; (2) unsafe Rust forms only **`&*ptr`**, never `&mut *ptr` — so a shared `&NdtEngine` is
  sound across concurrent ROS callbacks without an external lock. See [[ndt-engine-ffi-locking]].
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
