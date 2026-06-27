# NDT engine — WCET audit (E4e, audit slice)

`rust-realtime-review` WCET-audit of the `autoware_ndt_scan_matcher_rs` NDT engine RT-critical path
(E4a–d). Records boundedness evidence and residual risks; drives the E4e hardening slice. Re-run after
any change to `src/ndt.rs` / `src/derivatives.rs` / `src/transform.rs` / `src/kdtree.rs`.

**Scope.** RT-critical path = `align` loop → per iteration: `svd_solve` (nalgebra fixed-size SVD),
`se3_matrix_f32` + `transform_cloud_f32` (f32 cloud transform), `compute_derivatives` (per-source-point
loop: `VoxelGridMap::radius_search` + per-cell `update_derivatives`). Control-plane (not RT) = map
build/update (`add_target` / `create_kdtree`). Serial; the no_std async backend is future work.

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
- **Locking / async.** None — serial, single-thread, no shared state in the frame. (ParReduce + the
  no_std async backend are later; they will add scheduling jitter and need their own audit.)
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
