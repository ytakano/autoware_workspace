# `autoware_ndt_scan_matcher` Rust migration — split-PR roadmap

## Context (why)

The Rust migration of `autoware_ndt_scan_matcher` is implementation-complete (branch
`ndt_in_rust_2_on_main`: **110 commits / 131 files / +31,700 lines** ahead of `origin/main`). A single
giant PR is unreviewable. This roadmap splits it into a **reviewable stacked-PR series**.

**Requirements (fixed by the user):**
1. **The original upstream C++ files must not change at all — neither content nor filename.** The
   C++/Rust switch happens **only at the CMake source-set selection** level via `NDT_USE_RUST`
   (OFF = compile only the original files; ON = compile the new Rust-path files).
2. Where relevant, each PR demonstrates C++↔Rust equivalence.
3. Branch off `main` and send the PRs in order.

**The current branch violates requirement #1.** Both the ON and OFF paths share an *edited*
`ndt_scan_matcher_core.hpp`, and the original `ndt_scan_matcher_core.cpp` is compiled in both modes
but has been gutted (−781 lines; `NdtBackend` typedef, added `rs_` member, changed method
signatures). `map_update_module.cpp` and `ndt_omp/estimate_covariance.{cpp,hpp}` are edited too, with
the extracted bodies moved into `_legacy` shell files. → **Even OFF no longer matches upstream at the
file level.**

So this roadmap is not "just split into PRs" — it **presupposes a C++ glue-layer re-architecture**
(restore the original files to upstream verbatim; isolate the ON path into a self-contained parallel
tree). The Rust crate itself (`autoware_ndt_scan_matcher_rs/`, +16.7k lines) is unchanged.

## Target architecture (originals untouched + parallel tree)

```
localization/autoware_ndt_scan_matcher/
├── include/…                 ← upstream, unchanged
├── src/                       ← upstream, unchanged
│   ├── ndt_scan_matcher_core.cpp      ← revert the _legacy extraction; restore upstream verbatim
│   ├── map_update_module.cpp          ← ditto
│   └── ndt_omp/estimate_covariance.*  ← drop the _math split; restore upstream verbatim
├── rust/                      ← NEW. Self-contained tree, compiled only when NDT_USE_RUST=ON
│   ├── include/…/ndt_scan_matcher_core.hpp   ← Rust node class definition (holds rs_) — new header
│   ├── src/ndt_scan_matcher_core.cpp          ← Rust node implementation
│   ├── src/{map_update_module, …_host, …_align, …_sensor}.cpp
│   └── ndt_backend.hpp / ndt_legacy_state.hpp / ndt_scan_matcher_rs.hpp consolidated here
├── autoware_ndt_scan_matcher_rs/   ← Rust crate (no changes)
└── CMakeLists.txt
     if(NDT_USE_RUST)  # exclude the original core/map_update TUs; use rust/ instead
     else()            # only upstream src/ + include/  (= byte-identical)
```

**Design keys:**
- **In-source documentation and comments must be self-contained.** Comments and doc-comments in both
  the autoware_core C++ and the NDT-in-Rust code must make sense on their own, to a reader who has
  never seen any planning material. **References to planning artifacts are forbidden in source code**,
  including: this roadmap file (`plan/ndt_pr.md`) and any other `plan/*.md`; stage/PR labels from this
  document (e.g. "Stage 0", "PR2"); and the migration phase/slice jargon left over from development
  (e.g. "Phase 5 sub-slice 2", "node port N4a", "engine port E6a", "案B", "roadmap foundation",
  "transitional"). Describe *what the code does and why*, not *where it sits in the migration plan*.
- **OFF = byte-identical to upstream** at the file level. `git diff origin/main` shows "OFF is the
  original code, verbatim" (new files are added, existing files unchanged).
- Putting `rs_` into the original header would be an edit, so **the ON path redefines the same class
  `NDTScanMatcher` in its own header**. ON and OFF are never compiled together, so there is no
  same-name clash (the rclcpp component registration
  `autoware::ndt_scan_matcher::NDTScanMatcher` still works as-is).
- Drop the `estimate_covariance_math.cpp` extraction. The differential tests obtain their C++
  reference by linking the **pristine `multigrid_ndt_omp` library** (no edits to the original files).
- Per the `ndt_backend.hpp` comment, **the ON runtime uses the Rust engine**, so the `rust/` tree does
  not need the C++ engine at runtime (only the differential tests do).

## Steps

### Stage 0 — re-architecture branch (`ndt_in_rust_3_clean`) — **DONE**

> **Stage 0 is NOT a pull request.** `ndt_in_rust_3_clean` is a local staging branch; its diff vs
> `main` is the whole ~31k-line port and is **never submitted as one PR**. Its only job is to produce
> the clean end-state tree that Stage 1 slices into small stacked PRs. Do not open a PR from this
> branch.

**Status: complete** (branch `ndt_in_rust_3_clean`, commit `9f61c598`). Only `CMakeLists.txt` differs
from upstream among tracked files; OFF builds + 18 fast tests green; ON builds + 109 tests
(differential + cargo) green; clippy clean both feature sets. A latent crate bug was fixed on the way
(`ffi_ptr.rs` `ffi_slice!`/`ffi_read!` recursive arms called themselves by bare name, breaking
path-invocation from other modules under `--features ros`). Integration/launch `test_cases/` are
OFF-only. Steps that were executed:

1. Restore the four original files (`ndt_scan_matcher_core.cpp`, `map_update_module.cpp`,
   `ndt_omp/estimate_covariance.{cpp,hpp}`) and the edited headers
   (`ndt_scan_matcher_core.hpp`, `map_update_module.hpp`, `estimate_covariance.hpp`) to **upstream
   verbatim** (fold the `_legacy` extractions back in). Verify against `git show origin/main:<path>`.
2. Move `_rust` / `_rust_host` / `_align_rust` / `_sensor_rust` / `map_update_module_rust` and their
   headers (`ndt_backend.hpp`, `ndt_legacy_state.hpp`, `ndt_scan_matcher_rs.hpp`) under `rust/` and
   make them **self-contained** (a dedicated header; cut the dependency on the original header).
3. Rewrite `CMakeLists.txt` to the "source-set selection" form. Differential tests link the pristine
   `multigrid_ndt_omp`.
4. **Scrub in-source comments/docs to be self-contained** (see Design keys): remove every reference to
   planning artifacts from the `rust/` C++ glue, the Rust crate, and the tests — plan file names,
   stage/PR labels, and phase/slice jargon ("Phase … sub-slice …", "node port N…", "engine port E…",
   "案B", "roadmap foundation", "transitional", etc.). Rewrite each such comment to describe what the
   code does and why. (Grep for `plan/`, `Phase `, `sub-slice`, `node port`, `engine port`, `roadmap`.)
5. **Verify:** `git diff origin/main -- localization/autoware_ndt_scan_matcher/src
   localization/autoware_ndt_scan_matcher/include` (excluding `rust/` and CMake) is **empty**.
   OFF and ON both build green; all ctests green.

### Stage 1 — carve into the PR series

The full branch is ~31k lines, so a single PR is unreviewable. It is sliced into ~16 **stacked** PRs
cut from `main`, each **≤ ~3k lines** and **self-contained: code + the test that proves it matches
C++**.

**Stacked = each PR's base is the previous PR**, so a reviewer sees only that PR's own increment
(~1–3k), never the cumulative 31k:

```
main ← P1 ← P2 ← P3 ← … ← P16      each PR's shown diff = its own delta only
```

Two rules make this work:

**Rule 1 — every feature PR carries its own equivalence test.** Two test kinds, different homes:
- **Crate cargo tests** (`#[cfg(test)]`, `tests/*.rs`; assert against C++-derived golden values or
  mathematical properties) build with `cargo test` alone — they ride along from the very first crate
  module PR.
- **C++ differential gtests** (`test/*.cpp`; run the live C++ engine and the Rust FFI on identical
  input and compare) need the Corrosion/`NDT_USE_RUST=ON` build, so they ride from the wiring PR (P1)
  onward.

**Rule 2 — wiring comes early; the node swap comes last.** P1 wires Corrosion + the crate + the
cargo-test CTest, but `NDT_USE_RUST=ON` still builds the **original C++ node** plus the crate and its
differential tests. The engine-level differential gtests (link `multigrid_ndt_omp` + crate, not the
node) therefore run from P1 on. Only the final node-migration PRs flip ON to compile the `rust/` node;
the end state equals Stage 0.

Bottom-up so each PR compiles and `cargo test` is green:

| PR | Content (new files) | Original-C++ change | Equivalence test in this PR |
|---|---|---|---|
| P1 | Crate scaffold (Cargo/build.rs/cbindgen/wrapper, `lib.rs`) + **Corrosion/CMake wiring** + cargo-test CTest; ON still builds the original node | **CMakeLists.txt only** | OFF/ON both build green; cargo test green |
| P2 | Math foundation: `transform`, `helper`, `convergence`, `derivatives` | none | cargo tests; `test_convergence_verdict` |
| P3 | `voxel_grid` + `kdtree` | none | cargo tests; `test_voxel_grid` |
| P4 | NDT align (`ndt.rs`) | none | cargo tests; `test_align` |
| P5 | Engine handle (`engine.rs`) | none | cargo tests; `test_ndt_engine`, `test_node_run_align` |
| P6 | Covariance (`covariance`, `cov_estimate`) | none | cargo tests; `test_estimate_covariance_multi`, `test_estimate_pose_covariance` |
| P7 | TPE (`tpe.rs`) | none | cargo tests; `test_tpe_ffi` |
| P8 | FFI layer (`ffi_ptr`, `ffi`, `ffi_host`, `host`, `scan_matcher`) | none | cargo tests |
| P9 | Node state (`node`, `node_handle`, `pose_buffer`, `node_map_update`) + `rust/` handle glue | none (in `rust/`) | `test_ndt_scan_matcher_rs_handle`, `test_regularization_buffer`, `test_initial_pose_buffer` |
| P10 | Map-update (`node_map_update` glue + `rust/` map-update) | none | `test_map_update_verdict`, `test_map_update_state` |
| P11 | Align service (`node_align_service`) + `rust/` align glue | none | `test_ndt_align_service_decision` |
| P12 | Sensor callback (`sensor_points`) + `rust/` sensor/host glue | none | `test_sensor_points_prepare`, `test_sensor_points_match`, `test_node_pose_callbacks` |
| P13 | **Node swap**: ON compiles the `rust/` node instead of the original (Stage-0 end state) | **CMakeLists.txt** (source selection) | full ON suite green; OFF still upstream |
| P14 | no_std / `mt` / WCET / zero-alloc (`examples/`, `tests/concurrency.rs`, `tests/zero_alloc.rs`) | none | `concurrency.rs`, `zero_alloc.rs` |
| P15 | Benchmarks (`bench/`, `NDT_BUILD_BENCH` default OFF) | none | — |
| P16 | Design book (`doc/book/`) | none | — |

→ **Only P1 and P13 touch the original C++, and only `CMakeLists.txt`** (wiring, then source
selection). Everything else is new files. `doc/book` (P16) and `bench` (P15) carry no equivalence test.

### Stacking mechanics
- Stack each branch on the previous: `main` ← P1 ← P2 ← … (set each PR's GitHub base to the prior PR).
- Each commit: `git commit -s --no-gpg-sign`, no `Co-Authored-By` trailer (DCO).
- Merge in order; after a lower PR merges, retarget the next PR's base to `main`.
- CI runs **both** OFF (proves upstream parity) and ON (runs the differential tests) on every PR.

## Verification

- **Originals untouched (holds now):** among files tracked on `origin/main`, only `CMakeLists.txt`
  differs; every `src/`/`include/`/`test/` original is byte-identical.
- **Per PR — both configs:**
  - OFF: `bash -c 'source /opt/ros/humble/setup.bash; colcon build --packages-select
    autoware_ndt_scan_matcher --cmake-args -DNDT_USE_RUST=OFF'` — proves upstream parity.
  - ON: same with `-DNDT_USE_RUST=ON` — builds the crate + runs that PR's differential + cargo tests.
  - `./test.sh --packages-select autoware_ndt_scan_matcher` (fast math:
    `--ctest-args -R 'test_estimate_covariance|test_ndt_scan_matcher_helper'`).
- **Env note:** the interactive shell is zsh — run builds via `bash -c` so `setup.bash` sources
  correctly. For a direct `cargo … --features ros`, set
  `ROS_INCLUDE_DIRS=/opt/ros/humble/include/geometry_msgs`.
- **OFF preserves upstream behavior** (existing launch / `standard_sequence_*` tests, OFF-only).

## Open questions (confirm before implementing)

1. **PR destination** — the fork (ytakano/autoware_core) main, or upstream (autowarefoundation)?
   Going straight to upstream imposes stricter per-PR independent-build-green and C++-footprint
   minimization demands.
2. **Granularity of the big PRs** — P5 (`engine.rs`, ~2.7k) and P11 (`node_align_service`, ~3.2k) are
   the largest cohesive units; split further if a hard per-PR line cap is required.

_(Resolved: re-architecture done by Claude on `ndt_in_rust_3_clean`; parallel tree lives under
`rust/`.)_

---
Related: `plan/ndt_bench.md` (benchmarking roadmap)
