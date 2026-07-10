# NDT engine — WCET audit (E4e, audit slice)

`rust-realtime-review` WCET-audit of the `autoware_ndt_scan_matcher_rs` NDT engine RT-critical path
(E4a–d). Records boundedness evidence and residual risks; drives the E4e hardening slice. Re-run after
any change to `src/ndt.rs` / `src/derivatives.rs` / `src/transform.rs` / `src/kdtree.rs`.

**Scope.** RT-critical path = `align` loop → per iteration: `svd_solve` (nalgebra fixed-size SVD),
`se3_matrix_f32` + `transform_cloud_f32` (f32 cloud transform), `compute_derivatives` (per-source-point
loop: `VoxelGridMap::radius_search` + per-cell `update_derivatives`). Control-plane (not RT) = map
build/update (`add_target` / `create_kdtree`) **and the multi-NDT covariance estimation**
(`cov_estimate.rs`: `propose_poses_to_search` + `estimate_xy_covariance_by_multi_ndt[_score]`, which
run once per localization frame, re-align/score per candidate, and allocate `Vec`s — not the RT hot
loop). Serial; the no_std async backend is future work.

## Boundedness table

| RT path | Operation | Bound | Evidence | Residual risk |
|---|---|---|---|---|
| `align` | outer iterate | ≤ `max_iterations` (default 35) | **static** (loop guard) | — |
| `align` | per-frame heap alloc | **0** | **measured** — `tests/zero_alloc.rs`: 40 pts / 4 iters → 0 (after the fix below) | — |
| `compute_derivatives` | per-source-point loop | ≤ `P` (source len) | **documented** (caller voxel-downsamples) | `P` bound owned by the node |
| `compute_derivatives` | per-cell loop | ≤ `K` neighbors/point = `MAX_NEIGHBORS` (64) | **static** (`radius_search(max_nn = 64)` cap) | truncation if a real map exceeds 64 (monitor) |
| `radius_search` | kd-tree traversal | worst-case **O(N_leaves)** | **static** (recursion may visit all nodes) | **accepted residual** (benign for physical maps) |
| `svd_solve` | 6×6 SVD | fixed internal iterations | **static** (`SMatrix`, stack) + measured (no per-call alloc) | the one O(1) alloc above |
| `transform_cloud_f32` | per-point transform | O(`P`), reused buffer | **static** | — |
| `compute_{angle,point}_derivatives`, `update_derivatives` | fixed-size matrix math | O(1) | **static** (`SMatrix`) | — |
| `VoxelGridMap::leaf(idx)` | flat-Vec lookup | O(1) | **static** (`flat_leaves.get`) | — |

Bound classes: *static* = from code structure / type capacity; *documented* = claimed by a
constant/caller and validated elsewhere; *measured* = observed under test, **not a proof**.

## Audits

- **Allocation.** Per-frame steady state: **0** (measured, `tests/zero_alloc.rs`, after the hardening
  fix below). `compute_derivatives` is 0; the result `Vec`s + `trans_cloud` + `neighbor_idx` are
  pre-reserved/reused; `derivatives_at` uses `mem::take` (no alloc); the fixed-size 6×6 SVD is
  stack-only (probe-verified). Map build/update allocates — control-plane, acceptable.
- **Panic.** None in the RT path. The crate denies `unwrap`/`expect`/`panic`/`indexing_slicing`/
  arithmetic-overflow (rust-hardening); `align` uses `.get()` and `svd.solve(..).ok()`; indexing is
  into fixed-size `SMatrix` with constant indices.
- **Loop.** Outer ≤ `max_iterations` (static). Per-point ≤ `P` (documented — the node must cap the
  scan). Per-cell ≤ `MAX_NEIGHBORS` (64, static — `radius_search` cap). kd-tree recursion depth
  O(log N) via median split; worst-case traversal O(N_leaves) → accepted residual.
- **Data structures.** RT path = the kd-tree (`Vec<Node>` + `Vec<[f32;3]>`) and `flat_leaves`
  (`Vec`, O(1) `get`). **No `BTreeMap` in the RT path** — the `BTreeMap`s (`grids`, per-grid voxel
  index) are touched only in `add_target`/build (control-plane). (Corrects the earlier roadmap note.)
- **Locking / async.** The **serial** backend (default for WCET; the no_std/`--no-default-features`
  path) is single-thread, no shared state in the frame — the predictable baseline. The optional
  **rayon** backend (`parallel` feature, `num_threads > 1`) is **bit-for-bit identical** to serial
  (per-point-local contributions collected in point-index order, then folded in that order) but is
  **not** the WCET baseline: it allocates per frame (`ws.contribs` of `P` + per-worker neighbor
  buffers) and adds scheduling jitter, so it trades predictability for throughput. (The no_std async
  backend is still later.)
- **Drop.** Per-frame Drop is bounded: the reused `Vec`s are not dropped (kept across frames); SVD
  temporaries are fixed-size `SMatrix` on the stack. No large owned values leave the frame scope.

## Measurement / validation gaps

- **Frame-time benchmark exists** (`examples/wcet_frame.rs`; baseline below) but is synthetic /
  single-core / warm-cache — a regression watch, not a hardware WCET proof. No cold-cache or
  neighbor-dense-scan sweep yet.
- No **hardware** validation (cache/DMA/SMT/DVFS/IRQ interference) — `task response time = function
  WCET + scheduler + interrupt + blocking + memory interference`.

## Residual risks

1. **`P` (source point count)** is the caller's responsibility — the node must cap the downsampled
   scan; document at the node boundary (Phase N).
2. **kd-tree worst-case O(N_leaves) traversal** — **accepted (user-confirmed)**: benign for physical,
   roughly-uniform voxel maps with a fixed search radius. The structural bound (direct voxel-candidate
   + radius filter) is not planned unless a future need arises.
3. **`MAX_NEIGHBORS` truncation:** if a real map ever yields > 64 neighbors within the radius,
   `radius_search` returns the first-64 in traversal order (a deviation from C++'s unbounded set) —
   treat as a misconfiguration; monitor.
4. No **hardware** validation (cache/DMA/SMT/DVFS/IRQ) — a synthetic benchmark is a regression watch,
   not a hardware WCET proof.

## E4e hardening (update)

- **Per-frame allocation → 0** (was 1). Root cause was **not** the SVD (probe: nalgebra fixed-size
  6×6 `SVD::new`+`solve` allocates 0); it was a `trans_cloud` over-reserve in `align`
  (`reserve(len)` on a non-empty buffer → grow once). Fixed by reserving inside `transform_cloud_f32`
  after its `clear()`. `tests/zero_alloc.rs` now asserts `align == 0` allocations after warmup.
- **`K` bounded:** the three RT `radius_search` calls use `max_nn = MAX_NEIGHBORS = 64` (kd-tree
  early-exits at the cap → bounds collection and traversal-after-N). N ≫ the physical ≤27, so no
  truncation for real maps → `test_align` unchanged.
- **Frame-time baseline** (`cargo run --release --example wcet_frame`, synthetic 288-pt fixture, 5
  iters, single core / warm cache): min ≈ 0.42 ms, mean ≈ 0.43 ms, p99 ≈ 0.46 ms, p99.9 ≈ 0.67 ms,
  max ≈ 0.92 ms. Comfortably under a 10 Hz (100 ms) budget; a relative regression watch, not a proof.

## Verdict

The RT path is **panic-free, lock-free, zero-allocation per frame** (measured), with the outer loop
statically bounded (`max_iterations`) and the per-cell neighbor count bounded (`MAX_NEIGHBORS`). The
remaining residual is the kd-tree worst-case O(N) traversal (accepted for physical maps) and the
absence of hardware WCET validation. Suitable for the intended use; not a formally-proven hard-RT
bound under adversarial inputs / unvalidated hardware.

## Concurrency refactor update (engine becomes `Sync`; the giant lock is gone, ON path)

The align path is still **lock-free + 0-alloc per frame**, now without the C++ giant `ndt_ptr_` mutex:

- **Map/params read:** `align(&self)` does `ArcSwap::load_full()` (engine state) + a second for the
  regularization — each a wait-free atomic `Arc` refcount bump (O(1), no alloc, no lock). It replaces
  the previous **unbounded** wait on the giant mutex (held for the whole align / the entire map
  rebuild), so worst-case acquisition latency strictly improves.
- **Scratch:** the reused workspace + last result moved to a **thread-local** — exclusive per thread
  with no lock; the 0-alloc-after-warmup invariant holds (`tests/zero_alloc.rs` still passes; the free
  `align` keeps `&mut ws`).
- **Map publish:** map-update builds on a private staging engine and commits with **one** atomic
  `ArcSwap::store` (`commit_from`), so the align reader never observes a partial map.

**Residual RT risk (new, documented):** with `ArcSwap`, after a map-update store the **last reader to
drop the old `Arc<EngineState>` runs its `Drop`** — freeing the whole voxel map + kd-tree, an
*unbounded* (O(map size)) cleanup that can land on the **align thread** (not only the map-update
thread). It is rare (only when an align is the last holder of a just-superseded map) and map updates
are low-rate, and it is still strictly better than the old giant lock (which blocked the align for the
entire rebuild). Mitigation if hard-RT reclamation matters later: hand the superseded `Arc` to a
dedicated cleanup/map-update thread to drop (deferred reclamation), or an epoch/hazard scheme — keep
the heavy free off the align thread. Not done now (soft ~10 Hz use; the giant-lock removal is the win).

## M1 re-audit (2026-07-10, `ndt_wcet` branch — after the crate split, the hazard-scan fixes, and the `wcet-count` instrumentation)

Re-ran the WCET audit over the current engine crate (`engine/src`, post two-crate split). The
boundedness table above still holds, with these deltas:

- **Panic audit correction.** The earlier "no panic in the RT path" claim was **wrong**: the
  step-length port used `f64::clamp(step_min, step_size)`, which panics when a misconfigured
  `trans_epsilon / 2 > step_size` makes `min > max` — a panic source inside the align loop that this
  audit missed and the 2026-07-10 numeric-hazard scan caught. Fixed to the C++-parity
  `min(step_size).max(step_min)` (never panics, identical on the valid domain; pinned by
  `align_degenerate_step_bounds_do_not_panic`). Lesson recorded: lint gates do not flag `clamp`, so
  the audit checklist now includes the panicking std float APIs (`clamp`, `div_euclid`, …).
- **New O(1) guards on the align path** (from the hazard scan): the `asin` domain clamp in
  `matrix_to_euler`, the degenerate-config clamps in `gauss_constants` (both once per align), and
  the non-finite-pose verdict gate in `run_align_with` (16 × `is_finite` per align). All constant
  cost; no effect on the bound structure.
- **`wcet-count` instrumentation (M1, plan/ndt_wcet.md Layer 2).** Deterministic cost counters
  (`derivative_passes`, `points_processed`, `sum_neighbors`, `kd_nodes_visited`) on
  `AlignWorkspace`/`AlignResult`, populated via `PointContribution` and a visited counter threaded
  through the kd-tree walk. **Compiled out when the feature is off** — the threaded `&mut u64` is
  never written (verified: clippy `only_used_in_recursion` fires in the off build, suppressed with a
  cfg-gated `expect`), so the shipping hot path is untouched. Counters are identical between the
  serial and rayon backends (both fold the same per-point contributions;
  `parallel_counters_match_serial`). The Layer-1 analytic bound is now a machine-checked property
  (`tests/wcet_bounds.rs`, proptest, 64 cases): `passes ≤ iter+1`, `points = passes × P`,
  `neighbors ≤ points × MAX_NEIGHBORS`, `kd_nodes ≤ points × leaves`.
- **Residuals updated for M2** (unchanged in substance, now scheduled): (a) first-frame/growth
  allocation — `AlignWorkspace::new()` starts empty, so the zero-alloc invariant is *after warmup*;
  M2 adds worst-case pre-reserve and a first-frame zero-alloc test. (b) kd-tree recursion — depth
  is O(log N) by the median build (stack usage bound), traversal worst-case O(N_leaves) accepted;
  M2 converts the walk to an explicit fixed-size stack (order-preserving, oracle-tested) so the RT
  path is recursion-free. (c) `MAX_NEIGHBORS` truncation and hardware validation — unchanged.

## M2 (2026-07-10, `ndt_wcet` branch — Layer-1 prerequisites + adversarial fixtures + harness)

Closes the two M1 residuals scheduled above and adds the frozen-fixture plumbing
(plan/ndt_wcet.md M2).

- **First-frame zero-alloc (WCET "hard zero").** `AlignWorkspace::with_capacity(max_points)`
  (neighbor_idx → `MAX_NEIGHBORS`, trans_cloud → `max_points`, contribs → `max_points`) and
  `MatchScratch::with_capacity(max_points, max_iterations)` (also pre-reserves the 3 per-iteration
  `AlignResult` Vecs to `max_iterations + 1`). `tests/zero_alloc.rs` now asserts **zero
  allocations including the first frame** for both the free `align` and the
  `NdtEngine::align_with` path (a growth event is a WCET spike, so amortized warmup was not a
  bound).
- **Recursion-free RT path.** `KdTree::radius_search` now runs an iterative walk with a fixed
  `[usize; 64]` stack (`MAX_STACK = 64` ≥ ⌈log₂N⌉+1 by the median build — overflow unreachable;
  guarded without panic). **Exact visit order preserved** (near subtree first, far deferred LIFO):
  neighbor order feeds float summation order = bit-exactness. The recursive walk is kept under
  `#[cfg(test)]` as an oracle; `iterative_matches_recursive_oracle_exact_order` checks exact-order
  equality on random trees (n ∈ {0,1,2,3,7,64,257,800} × 24 queries × max_nn ∈ {0,1,3,64}).
  Same-day A/B on the synthetic fixture (taskset, 8k frames): recursive mean ≈ 531 µs → iterative
  ≈ 466 µs (~12 % faster; the tree-node hot loop no longer pays call overhead).
- **Frozen fixture format** (`engine/src/fixture.rs`, std-gated): magic `NDTFIX01`, little-endian;
  map stored as **tiles** (one `add_target`/id each) because the multi-grid map keeps one voxel
  grid per tile — overlapping tiles are the only way to drive per-point `K` to `MAX_NEIGHBORS`
  (a single tile geometrically caps `K` at the ≤ 8 voxels sharing a corner when radius = leaf
  size). C++-readable with a few `fread`s (M4). Sanity caps: ≤ 4096 tiles, ≤ 50 M points.
- **Adversarial fixtures** (`engine/examples/wcet_fixtures.rs` → `bench/fixtures/*.ndtfix`):

  | fixture | construction | map/src pts | iter | K̄ | kd nodes/pt |
  |---|---|---|---|---|---|
  | `dense_neighbors` | 8 overlapping tiles, centroids hugging shared 2×2×2-block corners, ε-guess + tiny ε_trans | 18432/1500 | **30** | **64.0** (= cap) | 142.9 |
  | `max_iterations` | rough random surface, trans_epsilon 1e-10 | 3200/1200 | **30** | 2.7 | 35.5 |
  | `cache_hostile` | 60×60-voxel map, source shuffled across 120 m | 28800/2000 | 3 | 3.0 | 67.5 |
  | `subnormal` | σ≈0.05 clusters (icov≈360), source on 1.99 m shell → `exp` → f64 subnormals | 1200/1000 | **30** | 0.7 | 15.9 |

- **Harness** (`wcet_frame.rs` fixture mode, `WCET_FRAMES` env): first HWM numbers (this container,
  taskset -c 2, 300 frames, serial, feature off):

  | fixture | p50 | p99 | max |
  |---|---|---|---|
  | `dense_neighbors` | 397.6 ms | 424.6 ms | 425.5 ms |
  | `max_iterations` | 31.3 ms | 33.9 ms | 42.8 ms |
  | `cache_hostile` | 7.7 ms | 11.7 ms | 12.1 ms |
  | `subnormal` | 7.9 ms | 8.4 ms | 9.0 ms |

  `dense_neighbors` (K = 64 × 30 iterations, the compound Layer-1 worst case) is ~50× the
  iteration-only fixture — confirming `N_iter × P × K` as the dominant WCET product term. These are
  container numbers (relative shape, not a hardware bound); with-counters runs match within noise.
- **Deferred (unchanged):** direct ≤ 27-voxel probe (changes neighbor sets → breaks bit-exactness);
  hardware measurement (M5 second half).

## M4 (2026-07-10, `ndt_wcet` branch — C++ comparison on the frozen worst set)

Pipeline: `bench/run_wcet.sh` = colcon build (Release, NDT_USE_RUST=ON, NDT_BUILD_BENCH=ON) →
Rust counters (`wcet_frame`, WCET_JSON) → `ndt_bench_replay --fixture` (both engines, identical
buffers, 100 aligns + 10 warmup, serial, taskset -c 2) → LD_PRELOAD allocation pass
(`bench/alloc_count.c`) → `bench/wcet_report.py`. Container: Ryzen 9 5900HX, GCC 11.4, rustc 1.96.

- **Equal-work gate: 6/6 fixtures pass** — `iteration_num` identical C++ vs Rust on every frozen
  fixture (incl. both search outputs), so the timing comparison is algorithm-fair and the
  counter-derived worst inputs transfer to C++ as designed (bit-exactness).
- **Headline: Rust ≤ C++ on the max of every fixture** (max ratio Rust/C++):

  | fixture | C++ max (ms) | Rust max (ms) | ratio |
  |---|---|---|---|
  | search_00 (union worst) | 876.3 | 608.5 | **0.69** |
  | search_01 | 614.0 | 523.3 | 0.85 |
  | dense_neighbors | 597.0 | 399.4 | 0.67 |
  | max_iterations | 93.6 | 31.3 | 0.33 |
  | subnormal | 58.0 | 7.7 | **0.13** |
  | cache_hostile | 20.5 | 8.2 | 0.40 |

  The plan's deliverable — "the port did not regress WCET on any fixture" — holds with margin.
  The `subnormal` fixture is the outlier (7.9×): the subnormal-`exp` timing hazard hits the C++
  engine far harder than the Rust one on this hardware.
- **Allocation:** C++ performs **88 k–682 k heap allocations per align** (search_00: 682,248/align;
  measured by the interposer); Rust measures **0** in the same harness — consistent with the
  zero_alloc.rs proof. Root cause identified below (per-point inner-loop vectors, ≈ 11
  mallocs/point/pass — NOT per-align temporaries). This is a first-order WCET risk on the C++
  side (allocator latency is unbounded under fragmentation/contention) that the Rust engine
  structurally does not have.
- **Unit-cost regression** (`T_p50 ≈ a·Σneighbors + b·kd_nodes + c`, R² ≥ 0.997 both):
  kernel eval a = 133.2 ns (C++) vs **46.9 ns (Rust)** — 2.8× cheaper per derivative kernel;
  kd node b = 25.6 ns (C++) vs 37.7 ns (Rust) — C++'s per-node traversal is cheaper, but the term
  is second-order on the worst set. (Rust's negative intercept c = −12.6 ms is an extrapolation
  artifact of the small n=6 fit, not a physical cost.)
- **Gumbel pWCET (M5 EVT half, documented approximation):** block-maxima (n=10) moment fit per
  fixture/engine; on the union worst `search_00`, p=1e-9 extrapolates to 899.7 ms (C++) vs
  629.2 ms (Rust); β is small everywhere (≤ 1.3 ms) — warm-cache tails are tight, the residual
  spread is interference, not algorithm. **Not a certified pWCET** (one container, warm cache,
  moment fit); the hardware half of M5 (bare-metal AArch64/x86_64 + interference co-runner)
  remains pending.

### C++ allocation root cause (2026-07-10 follow-up): ≈ 11 mallocs per point per derivative pass

The interposer counts decompose exactly as **allocations ≈ 11 × P × derivative_passes** on every
fixture — so the source is the per-point inner loop, not per-align temporaries:

| fixture | allocs/align | ÷ (passes × P) |
|---|---|---|
| search_00 | 682,248 | 682248 / (31×2000) = **11.0** |
| dense_neighbors | 511,748 | / (31×1500) = **11.0** |
| max_iterations | 409,403 | / (31×1200) = **11.0** |
| cache_hostile | 88,032 | / (4×2000) = **11.0** |
| subnormal | 292,038 | / (31×1000) = 9.4 (points with zero neighbors take the early-return path) |

Three stacked layers, all verified in this repo's sources (upstream, byte-identical — report only,
do not fix):

1. **Derivative loop body** — `src/ndt_omp/multigrid_ndt_omp_impl.hpp:427`: the OpenMP
   parallel-for constructs `std::vector<TargetGridLeafConstPtr> neighborhood;` **inside the loop
   body** (the simplest thread-safe pattern); `radiusSearch`'s `k_leaves.reserve(k)` then heap-
   allocates it for every point that has neighbors → ~1 malloc/point.
2. **radiusSearch wrapper** — `src/ndt_omp/multi_voxel_grid_covariance_omp_impl.hpp:263-264`:
   fresh local `std::vector<float> k_sqr_distances; std::vector<int> k_indices;` per call, resized
   by the kd query → ~2 mallocs/point.
3. **pcl::KdTreeFLANN::radiusSearch internals** — pcl/FLANN allocate nested per-query result
   containers (`vector<vector<int>>`-style wrappers + FLANN's internal result set) → the
   remaining ~8 mallocs/point.

Why it looks "free" in C++: the mallocs ride glibc's thread-cache fast path, so the *average*
cost is nearly invisible — but each one is a potential lock/page-fault/fragmentation stall, i.e.
exactly the unbounded-latency tail the WCET analysis exists to exclude. The Rust port removed all
three layers structurally: the neighbor buffer is hoisted into `AlignWorkspace.neighbor_idx`
(pre-reserved to `MAX_NEIGHBORS`, `clear()` keeps capacity), the kd search writes into the
caller-provided buffer, and `with_capacity` makes even the first frame allocation-free. A C++-side
fix would be hoisting `neighborhood`/`k_indices`/`k_sqr_distances` to thread-locals, but the
upstream files must stay byte-identical, so this is recorded as a finding only.

## P-sweep (2026-07-10 follow-up): WCET is affine in the source point count

Controlled sweep on the union-worst geometry (search_00 genome: 8 tiles, blocks=9, eps=1e-10)
regenerated at P ∈ {250, 500, 1000, 2000, 4000, 8000} — `wcet_fixtures --psweep`, counters
certify per-point work invariance at every P (iter = 30, Σnbr = P·64·31 exactly, kd/pt ≈ 193).
Replay: 50 aligns + 5 warmup per fixture per engine, taskset -c 2; equal-work 6/6.

Linear fit on the **max** series, `WCET(P) = slope·P + const`:

| engine | slope (µs/point) | intercept (ms) | R² | worst residual |
|---|---|---|---|---|
| C++ | 436 | 10.6 | **1.0000** | +14.2 ms at P=4000 (0.8 %) |
| Rust | 301 | 3.5 | **1.0000** | +3.5 ms at P=2000 (0.6 %) |

- **No cache knee over [250, 8000]** — the affine work model holds to <1 % residual; the
  Layer-1 prediction (P is the only multiplicative freedom; N_iter/K/T_solve unaffected) is
  confirmed empirically.
- **Parametric bound / budget inversion**: under the union-worst geometry on this host, a
  100 ms (10 Hz) budget admits P ≈ **320** points (Rust) / **205** (C++). Production maps do
  not reach K=64 × 30 iterations, so this is the adversarial floor, not a typical-case cap —
  but it is the number a voxel-filter configuration can be audited against.
- Slopes are consistent with the unit-cost regression: ~64 kernel evals × 31 passes/point ×
  (133 ns C++ / 47 ns Rust) ≈ 264 / 93 µs kernel-only, plus kd-search (~193 nodes/pt/pass).
- Paper: §5 "Scaling with the input size P" + Table/Fig (auto-generated from
  paper/data/{wcet_psweep,psweep_rust}.json); §6 threat updated (validated range; beyond-range
  extrapolation + pre-reserve capacity caveats).
