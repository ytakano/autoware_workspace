# NDT Rust — engine / node two-crate split roadmap

## Purpose (why)

The current Rust implementation `autoware_ndt_scan_matcher_rs` (a single crate) holds **both** the
NDT **engine** and the **ROS 2 node binding** (C-ABI + node orchestration). Split it into:

- an **engine crate** — ROS-free, `no_std`+`alloc`, reusable on awkernel;
- a **node crate** — ROS 2 / `std`, consolidating all the C++ C-ABI.

This is the natural end-state of design requirement 3 in the `ndt-rust-port` memory ("core logic must
stay no_std-capable so the final artifact is reusable on awkernel").

## Decisions (2026-07-09, by the user)

1. **The engine crate is pure Rust** (no `extern "C"` at all). The C-ABI shims currently embedded in
   the engine-side modules (~90 `AwNdtEngine*` handle shims plus the pure-function shims; ~109 total)
   **all move to the node crate** as thin wrappers over the engine's Rust API
   (`NdtEngine::align/result/...`). → This matches the Phase 8 end-state (C++ calls only the node
   handle) and is the cleanest separation.
2. **Timing: after Phase 8 completes.** The node port is still in progress and C++ transitionally
   calls the engine C-ABI **directly** (`_ndt_engine_update_map` / `_has_target` /
   `_get_current_map_ids` / `_engine`, etc.). Splitting once Phase 8 removes `NdtRustAdapter` — so C++
   calls only the node handle — avoids re-homing the engine C-ABI, minimizing cost. **For now this is
   planning only; no implementation.**

## Current state (the groundwork is already in place)

The crate is already logically split by feature gates. The gating in `lib.rs` maps almost directly
onto the crate boundary.

### Module → crate assignment

| engine crate (`no_std`+`alloc`, ROS-free) | node crate (`std` + ROS 2) |
|---|---|
| `ndt` `engine` `voxel_grid` `kdtree` `covariance` `cov_estimate` `derivatives` `transform` `tpe` `convergence` `pose_buffer` `scan_matcher` `host` (port traits) `helper` (pure part) `ffi_ptr` (see note※) | `node` `node_handle` `node_map_update` `node_align_service` `sensor_points` `ffi` `ffi_host` `ros_msgs` + **all the relocated C-ABI shims** |
| features: `std` / `parallel` / `mt` | depends on engine with `std,parallel` + `ros` (bindgen) |

- The engine-side modules are **un-gated** in `lib.rs` (they go into the `no_std` build).
- The node-side modules are all `#[cfg(feature = "std")]`. `ros_msgs` is `#[cfg(feature = "ros")]`.
- The portable seam `host`/`scan_matcher` already exists, and
  `examples/{tokio_ndt,threads_ndt,wcet_frame}.rs` already drive the engine without ROS.

※ `ffi_ptr` (audited pointer helpers + `ffi_ref!`/`ffi_mut!`/`ffi_slice!` macros, core+alloc) is
C-ABI-only. Under decision 1 (all C-ABI to node) it **goes to the node crate**. The engine crate,
being pure Rust, no longer needs raw-pointer handling.

## Reverse-flow edges (engine → node) — must be untangled first

There are very few real code-level reverse dependencies. Clear these before the split.

1. **`engine.rs` → `crate::node::AwConvergenceVerdict`** (real code, L1393/1404/1484). An engine
   result struct embeds a type defined in the node FFI module. **The only real code-level reverse
   dependency.** → Under decision 1 the C-ABI types (`AwConvergenceVerdict` etc.) belong to the node
   crate. Express the engine result with a pure-Rust type (e.g. a `convergence` Rust enum/struct) and
   convert to `AwConvergenceVerdict` in the node-side wrapper. Remove the `crate::node::*` references
   from the `engine.rs` result struct.
2. **`helper::count_oscillation_poses` → `ros_msgs`** (`#[cfg(feature="ros")]`-only, L169-). → Move to
   the node crate. The pure `count_oscillation(&[[f64;3]])` stays in the engine crate.
3. **Doc-comment references** (`[[crate::node]]` etc. in `convergence`/`ffi_ptr`/`host`; not compile
   dependencies). → Just relink at split time.

## C-ABI relocation size (cost of decision 1)

Current distribution of `extern "C"`/`no_mangle` (the part that moves from the engine side to the
node crate at split time):

| Module | Shims | Handling after relocation |
|---|---|---|
| `engine.rs` | 46 | `AwNdtEngine*` handle FFI → thin node wrappers (calling the engine Rust API) |
| `voxel_grid` | 20 | ditto |
| `tpe` | 13 | ditto |
| `covariance` | 12 | ditto |
| `lib.rs` | 9 | `_add`/`_rotate_covariance`/`_count_oscillation`/`_init_thread_pool` |
| `cov_estimate` | 6 | ditto |
| `ndt` | 2 | ditto |
| `convergence` | 1 | ditto |
| (node-side `node`/`node_handle`/`ffi_host`/`node_align_service`/`node_map_update`/`sensor_points`) | 93 | already in the node crate |

→ About **109** pure-function-style C-ABI shims move from the engine side. All are already hardened
and tested, so this is close to a mechanical move ("keep the Rust logic; relocate only the shim
files"). One redesign is required: the node crate owns the opaque-pointer management of the
`AwNdtEngine*` handle (`_new`/`_free`/`_clone`), while the engine crate just returns an `NdtEngine`
(a Rust value).

## Steps (after Phase 8 completes)

1. **Untangle the reverse edges** (items 1–2 above) inside the engine crate first (safe to do even
   before the split).
2. **Extract the engine crate**: move the un-gated modules into a new crate `autoware_ndt_engine_rs`
   (working name). Remove all `extern "C"` and fix the pure-Rust API. Port the `no_std`/`mt`/`parallel`
   features. Move the no_std gate (CI) and `examples/` here.
3. **Restructure the node crate**: make `autoware_ndt_scan_matcher_rs` depend on the engine crate.
   Consolidate the relocated C-ABI shims into a node-side `ffi_engine` (working name) that wraps the
   engine Rust API. Keep `ffi_ptr`/`ffi`/`ffi_host`/`ros_msgs` in the node crate. Move cbindgen header
   generation to the node side.
4. **Corrosion / CMake**: C++ links only the node crate's staticlib (unchanged). The engine crate is
   just a Cargo dependency of the node crate and is invisible to CMake.
5. **Verification**: `./test.sh --packages-select autoware_ndt_scan_matcher`, the no_std gate, colcon
   build ON/OFF, and the differential tests (`standard_sequence_*`) must be unchanged before/after the
   split.

## Decision log

- 2026-07-09: confirmed by the user — engine = pure Rust / all C-ABI to node / after Phase 8.
- 2026-07-09: **IMPLEMENTED** (branch `ndt_in_rust_3_clean`, not yet committed). Engine crate name =
  `autoware_ndt_rs`; layout = node crate as Cargo workspace root at its existing path (CMake
  `MANIFEST_PATH` unchanged) with the engine nested at `engine/`. Phase 8 turned out already complete,
  so no timing wait was needed. Verification: 84 exported C symbols identical (names + signatures)
  pre/post split; cbindgen regenerated with `parse_deps = true` + `include = ["autoware_ndt_rs"]`
  (opaque `AwNdtEngine`/`AwNdtVoxelGrid`/`AwNdtVoxelGridMap` resolve via the parsed dependency); colcon
  build ON (C++ compiles+links) and OFF both green; `colcon test` (functional + FFI differential
  gtests) exit 0; engine `cargo build` default/no_std/`mt`(+concurrency test)/clippy/test all green;
  node build + clippy green. New node modules: `ffi_{engine,ndt,voxel_grid,tpe,covariance,cov_estimate}`
  + `helper_ros`. Visibility widened: `NdtEngine::with_scratch` and `tpe::{INPUT,PRIOR}_DIMENSION` →
  `pub`; added `NdtEngine::map_ids()` (avoids leaking `EngineState`). 19 of the 84 symbols were already
  hand-declared C++-side (gtests + `ndt_scan_matcher_sensor_rust.cpp`), not emitted by cbindgen — a
  pre-existing arrangement, left unchanged.
- Related: `plan/ndt_pr.md` (split-PR roadmap), `plan/ndt_in_rust_next.md` (node port, Phases 5–8).
