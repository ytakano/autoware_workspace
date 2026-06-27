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
| `align` | per-frame heap alloc | **1, O(1)** (constant) | **measured** — `tests/zero_alloc.rs`: 40 pts / 4 iters → 1 alloc | SVD-internal; fixed solve → 0 |
| `compute_derivatives` | per-source-point loop | ≤ `P` (source len) | **documented** (caller voxel-downsamples) | `P` bound owned by the node |
| `compute_derivatives` | per-cell loop | ≤ `K` neighbors/point | **unknown** — `radius_search(max_nn = 0)` is unbounded | **`max_nn = N`** (hardening) |
| `radius_search` | kd-tree traversal | worst-case **O(N_leaves)** | **static** (recursion may visit all nodes) | **direct voxel-neighbor lookup** (hardening) |
| `svd_solve` | 6×6 SVD | fixed internal iterations | **static** (`SMatrix`, stack) + measured (no per-call alloc) | the one O(1) alloc above |
| `transform_cloud_f32` | per-point transform | O(`P`), reused buffer | **static** | — |
| `compute_{angle,point}_derivatives`, `update_derivatives` | fixed-size matrix math | O(1) | **static** (`SMatrix`) | — |
| `VoxelGridMap::leaf(idx)` | flat-Vec lookup | O(1) | **static** (`flat_leaves.get`) | — |

Bound classes: *static* = from code structure / type capacity; *documented* = claimed by a
constant/caller and validated elsewhere; *measured* = observed under test, **not a proof**.

## Audits

- **Allocation.** Per-frame steady state: **1 allocation, O(1)**, constant in `P` and iterations
  (measured). It is SVD-internal (3–4 SVD solves per frame produce only 1 alloc → not per-call; not
  per-point). `compute_derivatives` is **0** (measured); buffers are pre-reserved in `align`
  (`trans_cloud`, the three result `Vec`s) and reused; `derivatives_at` uses `mem::take` (no alloc);
  `transform_cloud_f32` reuses `out`. Map build/update allocates — control-plane, acceptable.
- **Panic.** None in the RT path. The crate denies `unwrap`/`expect`/`panic`/`indexing_slicing`/
  arithmetic-overflow (rust-hardening); `align` uses `.get()` and `svd.solve(..).ok()`; indexing is
  into fixed-size `SMatrix` with constant indices.
- **Loop.** Outer ≤ `max_iterations` (static). Per-point ≤ `P` (documented — the node must cap the
  scan). **Per-cell loop unbounded** (`max_nn = 0`) → residual. kd-tree recursion depth O(log N) via
  median split, but worst-case traversal O(N_leaves) → residual.
- **Data structures.** RT path = the kd-tree (`Vec<Node>` + `Vec<[f32;3]>`) and `flat_leaves`
  (`Vec`, O(1) `get`). **No `BTreeMap` in the RT path** — the `BTreeMap`s (`grids`, per-grid voxel
  index) are touched only in `add_target`/build (control-plane). (Corrects the earlier roadmap note.)
- **Locking / async.** None — serial, single-thread, no shared state in the frame. (ParReduce + the
  no_std async backend are later; they will add scheduling jitter and need their own audit.)
- **Drop.** Per-frame Drop is bounded: the reused `Vec`s are not dropped (kept across frames); SVD
  temporaries are fixed-size `SMatrix` on the stack. No large owned values leave the frame scope.

## Measurement / validation gaps

- No **worst-case frame-time benchmark** yet (max / p99.9 latency + jitter, cold vs warm cache,
  neighbor-dense scans). Required before any RT-readiness claim.
- No **hardware** validation (cache/DMA/SMT/DVFS/IRQ interference) — `task response time = function
  WCET + scheduler + interrupt + blocking + memory interference`.

## Residual risks (→ E4e hardening slice)

1. **Per-cell neighbor count unbounded** (`max_nn = 0`) → adopt `max_nn = N` + a fixed-capacity
   neighbor buffer; pick `N` from the voxel geometry (~27); count/log truncation (no silent cap).
2. **kd-tree worst-case O(N_leaves) traversal** → **direct voxel-neighbor lookup** (pcl DIRECT modes;
   `VoxelGridMap` already holds the integer voxel index) — structurally constant-bounded.
3. **1 O(1) allocation/frame** (SVD-internal) → a **fixed 6×6 solve** (hand/Cholesky/LDLᵀ) for a true
   zero-alloc frame; note it shifts the numeric result vs Eigen `JacobiSVD`, so re-tune the C++
   differential tolerance.
4. **`P` (source point count)** is the caller's responsibility — the node must cap the downsampled
   scan; document at the node boundary (Phase N).
5. **kd-tree recursion** is O(log N) depth — fine for normal stacks; make it **iterative** (explicit
   fixed stack) for small no_std task stacks.

## Verdict

The RT path is **panic-free, lock-free, and O(1)-allocation per frame** (1 alloc, measured), with the
outer loop statically bounded. It is **not yet hard-RT-ready**: the per-cell neighbor count and the
kd-tree traversal are unbounded in the worst case, there is one residual SVD allocation, and no
worst-case timing benchmark or hardware validation exists. Those are the E4e hardening slice.
