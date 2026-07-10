# WCET analysis of the NDT engine — C++ vs Rust — Roadmap

## Goal

Establish a defensible **worst-case execution time** for the NDT engine's per-frame `align` path,
and show the Rust port did not regress WCET anywhere relative to the C++ engine. The ideal —
measuring the maximum over *all* input patterns — is infeasible (the input space is continuous and
huge). This roadmap uses a **3-layer hybrid**: an analytic bound structure, a cost-counter-guided
worst-input search, and controlled measurement with extreme-value statistics; plus a C++
comparison that exploits the port's bit-exact equivalence.

**The WCET is conditional by construction.** It holds over a documented *operational envelope*:
`P ≤` the source-point cap, target voxel count within the int32 guard, finite validated inputs and
parameters (the 2026-07-10 hazard-scan guards define this boundary; the L1b incident — a 15 km
single-file PCD overflowing `MultiVoxelGridCovariance`'s int32 voxel index and silently emptying
the target — is the canonical example of an out-of-envelope input). Outside the envelope, inputs
are rejected/guarded, not timed. Serial (`num_threads = 1`) is the WCET baseline (parallel adds
scheduling jitter; it is a throughput option, bit-identical by design). WCET is **per platform**:
the x86_64 dev host and the no_std kernel target (x86_64/AArch64) are separate measurements.

Why the classic alternatives are out:

| Approach | Verdict |
|---|---|
| Static WCET tools (aiT-class) | Sound but target simple in-order cores (Cortex-R/M); on OoO x86_64/AArch64 with caches the hardware model is intractable and bounds are uselessly loose |
| Exhaustive input measurement | Infeasible (continuous input space) |
| Naive fuzzing with wall-time fitness | Time is noisy and platform-dependent — the search thrashes |
| Model checking / SMT over execution time | Intractable for FP-heavy numeric kernels; model checking earns its keep on *structural* properties instead (Layer 1) |

## The decomposition that makes it tractable

The engine was designed so that frame time decomposes (see `doc/book/src/rt/wcet.md`):

```
T_frame ≤ N_iter × [ Σ_{p ∈ P} ( T_search(p) + K(p) · T_kernel ) + T_solve ] + T_setup
```

The only data-dependent quantities are:

- `N_iter ≤ max_iterations` (config; the early exits only shrink it),
- `P` — source cloud size (bounded upstream by the downsample cap),
- `K(p) ≤ MAX_NEIGHBORS = 64` per point (`engine/src/ndt.rs:50`),
- the neighbor-search traversal (`engine/src/kdtree.rs::radius_search`, line 64).

Everything else is worst-case-constant: the per-point-per-neighbor kernel is straight-line FP code
(`derivatives.rs`), the solve is a fixed-size 6×6 SVD, and the hot path is allocation-free,
panic-free, and recursion-free except the kd-tree (`doc/book/src/rt/panic-free.md`,
`zero-alloc.md`; enforced by `tests/zero_alloc.rs` and the lint gates). So "worst case over all
inputs" collapses to "worst case over (N_iter, P, K, traversal) plus the micro-architectural
worst (cache/branch/FP-assist behavior)" — a searchable space.

## Layer 1 — structural bound (audit + proof)

Model checking's correct role: prove the **shape** of the bound, never the time.

- **WCET audit** of the align path (the `rust-realtime-review` skill's WCET-audit mode): every
  loop bounded by (max_iterations | P | MAX_NEIGHBORS | tree size), no alloc/panic/blocking, no
  unbounded retry.
- **Kani** (bounded model checking for Rust) on the small kernels at small sizes: prove
  panic-freedom and "cost counters ≤ the analytic formula" as machine-checked properties.
- **Prerequisites to land first** (the known E4e hardening items — without them the measured WCET
  is not the shipping WCET):
  1. **Worst-case pre-reserve** for `AlignWorkspace`/`MatchScratch`: today the buffers are
     *amortized* (`clear()` keeps capacity — `engine/src/ndt.rs:53` — so the first frame and any
     growth event allocate). Pre-reserve to the envelope maximum so **no** frame allocates,
     including the first; otherwise the harness must explicitly include first-frame/growth costs.
  2. **Bound the neighbor search** — the one non-compositional structure. `radius_search` is
     recursive with worst-case O(N) traversal (pruning can degenerate). Either switch the WCET
     path to the planned **direct voxel-neighbor lookup** (≤ 27 grid probes, analytic bound) or
     cap and *measure* the traversal count; make the kd-tree iterative (recursion depth ~log₂N
     today, still stack-dependent).

## Layer 2 — worst-input search (fuzzing's correct role)

- **`wcet-count` feature**: deterministic cost counters on the engine — iterations, Σ neighbors,
  kd-tree nodes visited, oscillation count. Counters are platform-independent and reproducible,
  which makes them a far better search fitness than wall time, and they double as the CI-checkable
  link to Layer 1.
- **Structure-aware search**: generate (map voxel layout, source cloud, guess, params) — not raw
  bytes — and maximize the counter vector. cargo-fuzz with a custom mutator works; a plain
  hill-climb/GA over the geometric generators is often more effective for numeric inputs
  (SlowFuzz/PerfFuzz idea, upgraded with deterministic fitness).
- **Hand-built adversarial fixtures** (near-worst by construction, cheap and instructive):
  - max-density map so every point collects `MAX_NEIGHBORS`;
  - a guess/landscape that never converges → full `max_iterations` (oscillation-inducing);
  - cache-hostile point orderings (voxel access pattern randomized across the map);
  - **subnormal-inducing geometry** — FP microcode assists cost ~100× per op on x86 and are the
    classic hidden WCET hazard of float kernels; detect via `perf -e fp_assist.any`. (Bit-exact
    porting means both engines hit them identically — see the C++ section.)
- **Property check**: proptest asserts counters ≤ the Layer-1 formula on every generated input —
  a violated bound is a bug, not a measurement.
- **Freeze the top-k worst inputs as fixtures** (the capture-once/replay-everywhere format from
  `plan/ndt_bench.md`): the same bytes feed the Rust harness, the C++ comparison, CI regression,
  and the kernel-target measurement.

## Layer 3 — controlled measurement + EVT (pWCET)

- **Protocol**: pinned isolated core (`taskset`/`isolcpus`), fixed frequency (performance
  governor, turbo off), SMT sibling idle, interrupt isolation; **cold and warm cache variants**;
  shipping configs — Rust `release` with `overflow-checks = true`, C++ colcon Release with the
  package's `-msse*` flags; `steady_clock`/`rdtscp` timing; perf counters
  (`cycles,instructions,cache-misses,fp_assist.any`), with instructions-retired as the
  determinism cross-check.
- **Numbers**: high-water mark × safety margin, **plus** MBPTA/EVT — fit a Gumbel/GPD tail to the
  per-frame distribution on the worst fixtures and report the **pWCET** at 10⁻⁶–10⁻⁹ exceedance
  (the standard practice where static analysis is infeasible).
- **Harness**: extend `engine/examples/wcet_frame.rs` (currently a synthetic-fixture relative
  regression watch reporting min/mean/p50/p99/p99.9/max) to load the frozen fixtures; record
  baselines in `porting_notes/ndt_wcet_audit.md` (the example's doc already designates that file).
- **Interference is a separate axis**: engine-in-isolation WCET first; then the ROS-host
  interference bound with a memory-bandwidth-thrashing co-runner. On the kernel target the
  interference profile differs (no threads, interrupt-disabled critical sections) — measure on
  target.

## C++ comparison

**Bit-exactness transfers the algorithmic worst case.** The differential tests prove identical
poses and iteration counts on the valid domain, which implies identical control flow per input:
same iterations, same neighbor sets, same oscillation — even the same FP operand stream, hence the
same subnormal-assist events (bit-exactness required verifying no FP contraction, so the operand
streams genuinely match). Consequences:

- The Layer-2 search needs **only Rust-side instrumentation**; its worst inputs are the C++
  engine's algorithmic worst inputs too. This also respects the hard constraint that upstream C++
  files stay **byte-identical** — no C++ instrumentation is possible or needed.
- Only the **micro-architectural** layer differs (PCL data layouts vs flat `[f32; 3]`, allocation
  behavior, PCL's voxel/kd structures vs the Rust ones, cache locality). That layer is exactly
  what per-engine *time* measurement covers — and it is where L1a/L1b already showed the Rust tail
  winning (max 1.5×).

**Vehicle**: extend `bench/ndt_bench_replay.cpp` — it already drives both engines from identical
buffers in one executable — with a **fixture-load mode** replacing the synthetic cloud. Per
fixture, assert `iteration_num` equality between engines (the equal-work fairness gate; a mismatch
means the input left the valid domain — report it separately, don't compare times).

**Measuring C++ without touching it**:

| Quantity | Method |
|---|---|
| Iterations | `getResult().iteration_num` (public API) |
| Hot-path allocations | **`LD_PRELOAD` malloc interposer** counting malloc/free inside the align call — no source change; contrast with Rust's `tests/zero_alloc.rs` proof of zero |
| Cache/branch/FP-assist | `perf stat` per engine phase |
| Neighbor/traversal counts | Not needed — bit-exactness makes the Rust counters authoritative for both |

**Fairness rules**: after measuring both engines on the shared worst set, run a light per-engine
refinement with time/instructions fitness (micro-architectural worst is engine-specific) and
measure both engines on the **union** of the two worst sets — never compare on one engine's home
turf only. OpenMP runtime overhead at `num_threads = 1` is real C++ cost and stays in; a
parallel-vs-parallel comparison (OpenMP vs rayon at matched thread counts) is a separate track,
not the WCET baseline.

**Reporting** — compare *unit costs*, not just endpoints: regress per engine

```
T ≈ a · (P · K̄ · iter)  +  b · iter  +  c
```

and compare the per-point-neighbor kernel cost `a` and the fixed overheads `b`, `c`. This
decomposition explains the already-observed split — L1a (synthetic, iter=10, kernel-dominated)
gave Rust ≈2.55×, L1b (real urban, iter=3, overhead-dominated) gave ≈1.16× at p50 but ≈1.56× at
max — and makes the WCET claim interpretable. Overlay the two EVT exceedance curves and the
p50/p99.9/max table (a `bench/gen_report.py` extension renders both engines already).

**Purpose framing**: on the ROS product both engines exist, so the deliverable is "the port did
not regress WCET on any fixture" with C++ kept as the CI reference on the frozen fixtures. On the
kernel target only Rust runs; the C++ comparison is evidence, not a shipping requirement.

## Phasing / milestones (each independently useful)

Implementation branch: `ndt_wcet` in autoware_core (from `ndt_in_rust_3_clean`), one commit per
milestone. Running record: `porting_notes/ndt_wcet_audit.md`.

- **M1 — `wcet-count` instrumentation + property checks** — **DONE** (commit 2418aff3): the
  counter feature, the analytic-bound proptest (`engine/tests/wcet_bounds.rs`), serial==parallel
  counter equality, and the Layer-1 WCET re-audit.
- **M2 — Layer-1 prerequisites + adversarial fixtures + harness** — **DONE** (commit 605228a1):
  `with_capacity` pre-reserve + first-frame zero-alloc proof; recursion-free iterative kd-tree
  (exact visit order, oracle-tested, ~12 % faster); frozen tile-aware fixture format
  (`engine/src/fixture.rs`, `NDTFIX01`); 4 hand-built fixtures (`dense_neighbors` pins K = 64 AND
  iter = 30) + `wcet_frame` fixture-replay mode; first HWM numbers recorded.
- **M3 — search** — **DONE** (commit c13f9bb8): counter-guided hill-climb
  (`engine/examples/wcet_search.rs`); confirmed the hand fixture saturates the analytic
  (iter, Σneighbors) maximum exactly (2000×64×31), then grew the free kd term +35 %; top-2 frozen.
- **M4 — C++ comparison** — **DONE** (see audit notes for numbers): `ndt_bench_replay --fixture`
  mode (equal-work `iteration_num` assert per fixture), `bench/alloc_count.c` LD_PRELOAD
  interposer (C++ allocs/align without touching upstream), `bench/run_wcet.sh` pipeline,
  `bench/wcet_report.py` (tail table + unit-cost regression + Gumbel pWCET).
- **M5 — pWCET + target hardware** — **HALF DONE**: EVT fitting + report generation live in
  `wcet_report.py` (moment-based Gumbel on block maxima, documented approximation). **Pending**:
  repeating the measurement protocol on the kernel target (AArch64/x86_64 bare metal) and with an
  interference co-runner on the host — requires target hardware, out of scope for this container.

## Cross-references

- `plan/ndt_bench.md` — the fixture format (capture-once, replay-everywhere), the L2/L3 harness
  this reuses, and the measured L1a/L1b results the unit-cost model must explain.
- `doc/book/src/rt/wcet.md`, `panic-free.md`, `zero-alloc.md` — the WCET contract this roadmap
  turns into numbers; `doc/book/src/quality/benchmarks.md` — published results.
- `porting_notes/ndt_wcet_audit.md` — the running baseline record.
- `plan/ndt_pr.md` — the split-PR roadmap; WCET work aligns with the bench/mt phases (P14–P15).
