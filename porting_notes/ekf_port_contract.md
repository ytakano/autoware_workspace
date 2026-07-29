# EKF localizer port-equivalence contract (C++ → Rust)

Governs the port of `autoware_ekf_localizer` (fork branch `ekf_in_rust`) and its embedded
`autoware_kalman_filter` dependency to the Rust crates `realtime_ekf_localizer` /
`realtime_kalman_filter` (realtime_core branch `ekf_localizer`). This document is the
**fail-closed source of truth** for what "behaviorally equivalent" means: every externally or
semantically observable value is listed here with an explicit comparison policy; anything not
listed is either explicitly excluded (with a reason) or a hard failure of the conformance run.

Scope of this phase: **pure-Rust core + conformance testing** driven by a scenario replay
(C++ `ekf_replay` CLI vs Rust `examples/ekf_replay.rs`). ROS node integration, FFI, TF output,
and closed-loop A/B are a later phase.

## 1. System under contract

State (latest block): `x = [X, Y, YAW, YAWB, VX, WZ]` (dim 6). The filter is a
`TimeDelayKalmanFilter`: extended state of `6 * extend_state_step` (default 50 → 300), full
dynamic covariance `P` (300×300). Auxiliary `Simple1DFilter` ×3 for z / roll / pitch.

Per tick (C++ `EKFLocalizer::timer_callback` → Rust `EkfLocalizerCore::tick`):

1. dt measurement (fake clock in replay): `dt = (now - last_predict_ns)/1e9`, clamp to 10.0 s
   if larger, warn-only branch if `dt > pose_smoothing_steps / ekf_rate`; jump-back in time
   skips accumulation and dt update.
2. `accumulate_delay_time(dt)` — shift delay table right, front = 0, add dt to older entries.
3. `predict_with_delay(dt)` — nonlinear bicycle-ish model + `predictWithDelay` block update.
4. Pose queue drain: exactly `n = queue.size()` iterations of `pop_increment_age()` +
   `measurement_update_pose`.
5. Twist queue drain: same with `measurement_update_twist`.
6. Outputs: current pose (biased + unbiased), twist, pose covariance (36), twist covariance
   (36), yaw bias.

Measurement update decision chain (pose): delay gate (`delay_step >= extend_state_step`) →
NaN/Inf gate on `y = [x, y, yaw_offset]` → Mahalanobis gate (`distance > pose_gate_dist`) →
`updateWithDelay` (LLT failure or NaN/Inf gain rejects silently inside the KF). Twist is the
same chain with `y = [vx, wz]`, block `P[4..6,4..6]`, `twist_gate_dist`.

## 2. Observability matrix (in-scope observables)

Both sides emit one trace row per event (`predict` / `pose` / `twist`) in the shared CSV
format (§4). Every row/field below is compared; unknown events or missing fields fail the run.

| Observable | C++ point | Rust point | Policy |
|---|---|---|---|
| event kind + order | `EKFModule::trace_*` call sites | `ekf_module` trace records | exact (sequence) |
| `current_ns`, `measurement_ns` | fake clock / msg stamp | same | exact (u64/i64) |
| `delay_s` | `measurement_update_*` | same | float `rel_tol` |
| `delay_step` | `find_closest_delay_time_index` | same | **exact** (integer decision) |
| `delay_gate`, `mahalanobis_gate`, `accepted` | gate branches | same | **exact** (0/1) |
| `obs_x, obs_y, obs_yaw` (pose) / `obs_vx, obs_wz` (twist) | measurement after yaw offset | same | float `rel_tol`; yaw wrapped |
| `pred_*` (y_ekf at delay_step) | state block read | same | float `rel_tol`; yaw wrapped |
| `innovation_*` | `obs - pred` (yaw normalized) | same | float `rel_tol` (abs floor) |
| `mahalanobis` | `mahalanobis()` | same | float `rel_tol` |
| post state `x0..x5` (latest block) | `getLatestX` after event | same | float `rel_tol`; yaw wrapped |
| `P` diagonal `p0..p5` (latest block) | `getLatestP` after event | same | float `rel_tol` |
| `z, roll, pitch` (Simple1DFilter x) | filter state after event | same | float `rel_tol` |
| `z_var, roll_var, pitch_var` | filter var after event | same | float `rel_tol` |
| pose/twist message covariance (36) | `get_current_*_covariance` | same | covered via P diag + off-diag mapping tests (unit-level); replay compares P diag |
| queue sizes / aging | implied by event sequence (which measurements replay on which tick) | same | exact (sequence) |

Reason codes: a rejected update is attributed by the gate flags: `delay_gate=0` → delay
rejection; `delay_gate=1, mahalanobis_gate=0, accepted=0` with finite mahalanobis → gate
rejection; `delay_gate=1, mahalanobis_gate=0, accepted=0` with NaN mahalanobis → NaN/Inf
measurement rejection (C++ writes NaN for the mahalanobis field on that branch). An LLT /
non-finite-gain rejection inside `updateWithDelay` leaves `accepted=1` in the C++ trace but
the post-state equals the pre-state; the differential run still catches any divergence via the
post-state fields (documented C++ trace quirk, reproduced by the port's trace).

### Explicit exclusions (with reasons)

- Diagnostics strings/topics, warning throttle messages: log-only, no feedback into state.
- `EKFDiagnosticInfo` maxima (delay_time, mahalanobis): diagnostic aggregation only; the
  per-event values they aggregate are compared.
- ROS QoS, agnocast wrappers, tf lookup/broadcast, publishers: out of scope this phase.
- Processing-time topic, stopwatches: wall-clock.
- `get_transform_from_tf` failure path in `callback_initial_pose` (replay uses identity).
- Header `frame_id` checks: warn-only branches, no state effect.

## 3. Numeric policy

- **Decisions are exact**: event kind/order, `delay_step`, all gate booleans, integer
  timestamps. No tolerance ever hides a decision flip.
- **f64 chains** (state, covariance, innovation, mahalanobis, 1D filters):
  `|a-b| <= rel_tol * max(|a|,|b|) + scale_floor` with
  `scale_floor = abs_floor_scale * S_row`, `S_row = max(|x0|, |x1|, 1)` (the row's dominant
  position magnitude) and `abs_floor_scale = 1e-12`. Rationale (error analysis, not observed
  drift): the shared covariance recursion couples every field to the position states, so a
  per-op rounding difference is bounded by `~ulp(position) ≈ 2.2e-16 * |x|`; fields formed by
  cancellation (innovations) or cross-coupling through `P`/`K` (wz, vx, mahalanobis) inherit
  *absolute* drift at that scale even when their own values are near zero. `1e-12 * S_row`
  (≈ 4500 ulp of the dominant scale) bounds the accumulated drift with ~20× headroom over the
  worst measurement while staying ≥ 4 orders below every gate threshold.
  NaN == NaN is equal (rejection-branch fields); ±Inf compare by sign.
- **Yaw fields** are compared after wrapping the difference to (-π, π]
  (`atan2(sin(a-b), cos(a-b))` metric), same `rel_tol` policy on the wrapped difference
  against an absolute-angle floor of `1e-9` rad.
- Eigen vs nalgebra do not produce bit-identical mat-mul/Cholesky results; the tolerance is
  set from the Step 2 spike measurement, not from observed drift of the full run.

### Measured (Step 2 spike — TimeDelayKalmanFilter golden vectors)

Golden vectors: C++ `TimeDelayKalmanFilter` (dim_x=3, max_delay_step=5, constants from
`test_time_delay_kalman_filter.cpp`) driven through init → predictWithDelay → updateWithDelay
(delay 0 / 2 / 4) plus 3-predict sequence; full extended `x` (15) and `P` (15×15) dumped at 17
significant digits and compared element-wise against the Rust port.

- Measured (2026-07-28, g++ -O2 Eigen 3.4 vs rustc release nalgebra 0.33): `init`,
  `predictWithDelay` (single and ×3) — **bit-identical** (max rel 0.0). `updateWithDelay`
  (LLT solve path, delay 0/2/4) — **max rel 3.61e-15** (`P(6,6)` after `update_d2`,
  0.0038461538461538602 vs 0.0038461538461538464 ≈ 16 ulp). Regen:
  `porting_notes/ekf_conformance/spike/run_spike.sh`.
- Spike stop condition (`rel > 1e-6`): **not triggered**.
- **Frozen contract tolerance: `rel_tol = 1e-9`** — ~6 orders above the spike worst case,
  leaving headroom for the deeper 6-dim/300-dim EKF chains, still far below any gate
  threshold's discrimination band.
- End-to-end replay error (recorded at Step 5/6): see §7.

## 4. Trace format (shared CSV)

Header prefix (existing 20-column pose-trace format, unchanged):

```
current_ns,measurement_ns,delay_s,delay_step,obs_x,obs_y,obs_yaw,pred_x,pred_y,pred_yaw,
innovation_x,innovation_y,innovation_yaw,mahalanobis,delay_gate,mahalanobis_gate,accepted,
post_x,post_y,post_yaw
```

Extension columns (appended; both sides; `%.17g`):

```
event,x0,x1,x2,x3,x4,x5,p0,p1,p2,p3,p4,p5,z,roll,pitch,z_var,roll_var,pitch_var
```

- `event ∈ {predict, pose, twist}`.
- `predict` rows: `measurement_ns=0`, `delay_s=dt`, `delay_step=0`, obs/pred/innovation/
  mahalanobis = `nan`, gates/accepted = 1.
- `twist` rows reuse the pose columns positionally: `obs_x:=obs_vx`, `obs_y:=obs_wz`,
  `obs_yaw:=nan`, `pred_x:=pred_vx`, `pred_y:=pred_wz`, `pred_yaw:=nan`, innovations
  likewise, `post_x/post_y/post_yaw` keep their meaning (position state).
- `x0..x5` = latest state block after the event; `p0..p5` = latest P diagonal;
  `z/roll/pitch(+_var)` = Simple1DFilter state after the event.

## 5. Conformance corpus

1. **Synthetic scenarios** (deterministic, seeded generator
   `realtime_ekf_localizer/examples/gen_scenarios.rs`): straight drive, turn with yaw ±π
   wrap, delay-gate rejection (stale stamps), NaN injection (pose x / yaw quat / twist vx),
   Mahalanobis rejection (tight gate + far measurement), dt=0 tick, giant dt (>10 s clamp),
   jump-back in time, queue aging × smoothing interaction (bursts exceeding max queue),
   yaw_bias estimation enabled/disabled, zero-velocity twist below
   `threshold_observable_velocity_mps`.
2. **Real-data scenario**: measurements reconstructed from the frozen stack-replay pose trace
   (`stack_replay_results_reinit/rust2/ekf_pose_updates.csv`: `measurement_ns, obs_x, obs_y,
   obs_yaw`) + twist stream parsed from the rosbag
   (`loc_bag` `/localization/twist_estimator/twist_with_covariance`, CDR), driven at the
   original 50 Hz tick timeline.
3. Comparator: `porting_notes/ekf_conformance/compare_traces.py` (python stdlib) — exact
   fields first, numeric per §3, yaw wrapped; failures classified per scenario/event/field.
   Contract-coverage: every §2 field must be observed ≥ once per scenario class; missing
   fields fail.
4. Fixtures frozen with SHA-256 + regeneration script (`gen_fixtures.sh` pattern).

## 6. Gates (Step 6)

- `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` (std and no_std),
  `cargo test --workspace`, `bash coverage.sh` run clean in `realtime_core`.
- Differential run: 100 % decision agreement, all numerics within §3 across the corpus.
- Transcribed C++ unit tests (kalman_filter, time_delay_kalman_filter, state_transition,
  mahalanobis, measurement, covariance, numeric, aged_object_queue, simple_1d_filter,
  ekf_module) pass on the Rust side with contract policies.

## 7. Differential results (Step 5/6, frozen 2026-07-28)

Corpus: 12 synthetic scenarios (`gen_scenarios.rs`, seeds 1-12: straight, yaw_wrap,
delay_gate incl. stale twists, nan_inject ×4 injections, mahalanobis pose+twist, dt_zero,
dt_clamp >10 s, time_jump_back, queue_burst, yaw_bias_off, llt_reject non-PD R,
slow_velocity threshold override) + 1 real-data scenario (60 s window of the frozen stack
replay: 2952 ticks, 601 poses, 6021 bag twists) — **21,378 trace rows** total.

- **Decisions: 100 % agreement** (event kind/order, timestamps, delay_step, all gates,
  accepted) across all 13 scenarios, including all rejection branches (pose/twist delay
  gate, NaN/Inf, Mahalanobis, in-KF LLT rejection with the C++ discarded-bool quirk).
- Numerics: synthetic worst `max rel = 3.0e-10` (delay_gate innovation cancellation);
  real-data worst absolute drift `4.4e-11` on the 6.6e4-scale position chain (~3 ulp of
  scale, rel 6.6e-16), `1.6e-9` absolute on mahalanobis (rel 1.7e-10); tiny-magnitude
  cancellation fields (twist-row wz ≈ 6e-5) show abs ≤ 1e-11 (well inside the §3
  `1e-12 * S_row ≈ 6.6e-8` floor). All within contract policy.
- Comparator mutation audit (`compare_traces.py --self-test`): all decision flips, event
  reorder, row-count, NaN-vs-number, above-tolerance numeric and sub-floor drift cases
  behave as required.
- Fixtures frozen: `ekf_conformance/fixtures/scenarios.sha256` +
  `expected_cpp_traces.sha256`; regeneration is deterministic
  (`run_conformance.sh` verify mode passes twice from clean workdirs).

## 8. FFI integration conformance (fork `ekf_in_rust`, frozen 2026-07-29)

The EKF module boundary is integrated behind `-DEKF_USE_RUST=ON`
(`autoware_ekf_localizer_rs` staticlib + `ekf_module_rs.cpp` adapter; selector header is the
single preprocessor seam). Post-upstream-merge baseline (HEAD `f6ee1539`) verified first: the
C++ `ekf_replay` reproduces both frozen SHA manifests exactly (no drift; the discarded-update
fix PR is not merged, so the quirk-faithful semantics of §2 still hold).

- **Builds**: `EKF_USE_RUST=OFF` and `ON` (both with `EKF_BUILD_REPLAY=ON`) build cleanly.
- **C++ test suite under the Rust backend**: 152/152 pass unchanged in both configurations
  (unit + diagnostics + both launch tests; no test was inapplicable).
- **FFI conformance**: the Rust-backend `ekf_replay` over the frozen 13 scenarios —
  100 % decision agreement vs the frozen C++ fixtures with the same per-scenario numerics as
  the native run (worst synthetic rel 3.0e-10; real-data within §3 policy), and every trace is
  **byte-identical** to the native Rust replay (`cmp`), as predicted (same core, same trace
  writer, now exercised through the C ABI).
- **Closed-loop smoke** (C++ NDT + Rust EKF, `install_stack_rust_ekf`, REINIT=1 watchdog,
  600 s, governor=performance): graph up; EKF output 29,878 poses over 597.5 s sim =
  **50.00 Hz**, inter-pose gap p99 = 20.0 ms, max 21.1 ms, zero gaps > 100 ms (no
  starvation); NDT 5,915 diags / 5,722 accepted (~10 Hz); peak RSS 1.39 GiB; watchdog:
  **0 reinit attempts** with EKF↔GNSS residual 1.28 m at shutdown — matching the frozen
  baseline cpp1, whose first reinit event occurs at ~1,318 s wall, well past this window.

### 8.1 Offline replay cost: execution time / heap allocations (measured 2026-07-29)

Setup: `ekf_replay` OFF-build (C++ Eigen) vs ON-build (Rust over FFI), pinned to one core
(`taskset -c 2`, all governors `performance`), N=10 runs after 1 discarded warmup. "compute"
subtracts a per-scenario parse-only baseline (same scenario with `tick` lines stripped —
parsing is byte-identical between backends). Timing rows are **untraced** (unopenable
`AUTOWARE_EKF_POSE_TRACE` path disables all trace formatting on both sides). Allocations via
an LD_PRELOAD interposer (bench/alloc_count.c extended with byte counting + exit dump),
net of the same parse-only baseline; bytes are gross requested, not live.

| scenario (events) | backend | median wall | compute | µs/event | net allocs | net MB | allocs/event | KB/event | peak RSS |
|---|---|---|---|---|---|---|---|---|---|
| realdata (11 859) | C++ | 711.1 ms | 651.2 ms | 54.9 | 261 485 | 2 380 | 22.0 | 201 | 11.3 MiB |
| realdata | Rust | 987.4 ms | 927.4 ms | 78.2 | 1 415 071 | 8 972 | 119.3 | 757 | 11.4 MiB |
| straight (1 200) | C++ | 113.3 ms | 69.8 ms | 58.1 | 26 140 | 242 | 21.8 | 201 | 11.7 MiB |
| straight | Rust | 143.0 ms | 98.5 ms | 82.1 | 143 140 | 908 | 119.3 | 757 | 11.4 MiB |
| queue_burst (1 000) | C++ | 104.1 ms | 59.9 ms | 59.9 | 22 433 | 166 | 22.4 | 166 | 11.7 MiB |
| queue_burst | Rust | 129.1 ms | 85.0 ms | 85.0 | 121 233 | 758 | 121.2 | 758 | 11.4 MiB |

- **Execution time**: the Rust backend is a consistent **~1.42× slower** on the filter
  compute across all three scenarios (~78–85 µs vs ~55–60 µs per event). Run-to-run spread
  is < 1 % (min ≈ median).
- **Heap**: neither side is allocation-free (dynamic 300-dim extended state). C++ ≈ 22
  allocs / ~200 KB per event; Rust ≈ 119 allocs / ~757 KB per event (**~5.4× calls,
  ~3.8× bytes**). The extra comes from nalgebra producing owned temporaries where Eigen
  uses lazy expression views (`.transpose()`, view `.into_owned()`, per-event
  latest-state/covariance snapshots for the trace record) — a known optimization headroom,
  not a semantic difference. Peak RSS is equal (~11.5 MiB): the temporaries are transient.
- **Trace-writing overhead** (excluded above): +150 ms on realdata for C++ (iostream
  `setprecision(17)` formatting) vs +12 ms for Rust — the traced/untraced split matters
  when comparing traced runs.
- **What this does/doesn't mean**: offline replay cost on one pinned core, including FFI
  marshaling for the Rust side; not the 50 Hz node's real-time budget. Worst mean per-tick
  cost (realdata, 2 952 ticks incl. update events): C++ ≈ 221 µs, Rust ≈ 314 µs — 1.1 % vs
  1.6 % of the 20 ms tick; the closed-loop smoke (§8) showed identical 50.00 Hz output and
  no starvation for the Rust backend.

### 8.2 Real-time hardening: allocation-free event path (measured 2026-07-29)

The Rust event path (realtime_kalman_filter + realtime_ekf_localizer, mirrored into the fork
vendor) was reworked onto preallocated scratch (extended-dim buffers sized at init, lazy
per-measurement-dimension pools, in-place gemm/`transpose_to` through the same nalgebra
kernels, a hand-rolled in-place LLT transcribed from nalgebra's `Cholesky::new`/`solve_mut`
loops, buffer-swap instead of buffer-replace), and the FFI layer now skips CSV serialization
entirely when no trace stream is open and reuses a handle-owned event buffer.

**Invariance**: the frozen 13-scenario corpus still passes (decisions 100 %, numerics within
§3) and the traces are **byte-identical to the pre-hardening Rust build** — the plan's
fallback clause was not needed (the hand LLT was verified bit-equal to `Cholesky::new` on
randomized 2×2/3×3 factors with 300-column solves; the covariance downdate deliberately
subtracts the fully-accumulated product once, because a β=1 gemm changes the rounding).
New gate: `realtime_ekf_localizer/tests/zero_alloc.rs` (counting global allocator) asserts
**0 allocations/event** after warmup for predict + accepted/rejected pose/twist updates and
the getter path. 178 workspace tests and 152 colcon tests (EKF_USE_RUST=ON) pass.

Re-measurement under §8.1 conditions (same harness, pinned core, performance governor,
N=10, parse-baseline subtraction, trace formatting disabled):

| scenario | backend | compute before | compute after | allocs/event before → after | KB/event before → after |
|---|---|---|---|---|---|
| realdata | C++ | 651.2 ms | 652.2 ms | 22.0 → 22.1 | 201 → 201 |
| realdata | Rust | 927.4 ms | **843.5 ms** | 119.3 → **0.53** | 757 → **0.04** |
| straight | C++ | 69.8 ms | 68.6 ms | 21.8 → 21.8 | 201 → 201 |
| straight | Rust | 98.5 ms | **85.3 ms** | 119.3 → **0.55** | 757 → **0.07** |
| queue_burst | C++ | 59.9 ms | 60.1 ms | 22.4 → 22.4 | 166 → 166 |
| queue_burst | Rust | 85.0 ms | **75.4 ms** | 121.2 → **0.45** | 758 → **0.07** |

- The residual ~0.5 allocs/event is the **replay harness's** per-`tick`-line
  `istringstream` parsing (absent from the no-tick parse baseline); the filter path itself
  is zero-allocation per the counting-allocator gate. The C++ backend is unchanged
  (~22 allocs / ~200 KB per event — Eigen dynamic temporaries).
- Rust compute improved 10–15 %; the C++ ratio drops from 1.42× to **1.25–1.29×** (the
  remaining gap is kernel-level gemm cost on these shapes, no longer allocation).
- Peak RSS: ~12.1 MiB (+ ~0.7 MiB for the two preallocated N×N scratch buffers).
- Closed-loop smoke re-run (C++ NDT + hardened Rust EKF, REINIT=1, 600 s, governor
  performance): 29,878 poses / 597.5 s = **50.00 Hz**, gap p99 = 20.0 ms, max 21.4 ms, zero
  gaps > 100 ms, 0 reinit attempts, EKF↔GNSS residual 1.27 m at shutdown, peak RSS
  1.35 GiB — indistinguishable from the §8 smoke.

### 8.3 Root-cause decomposition of the residual EKF slowdown (investigation, 2026-07-29)

Investigation only — no shipping code or numeric behavior changed; all perf/microbench code
lived in scratch. No hardware PMCs available (no perf/valgrind), so the attribution is by
wall-time A/B, per-op microbenchmarks, source reading, and `objdump`/Cargo.lock static
inspection. Conditions: §8.1 harness (`taskset -c 2`, governor **performance** — verified),
N=10 after warmup, parse-baseline subtracted, trace formatting disabled on every backend.
"native" is a throwaway crate driving the realtime crates directly with the trace populated
but not serialized (identical to the FFI untraced path).

**Exp 1 — layer split (µs/event).**

| scenario | C++ | native-Rust | FFI-Rust | native/cpp | ffi/cpp | FFI cost (ffi−native) |
|---|---|---|---|---|---|---|
| realdata | 55.9 | 65.5 | 70.8 | 1.17 | 1.27 | +5.3 |
| straight | 57.4 | 65.1 | 72.3 | 1.13 | 1.26 | +7.2 |
| queue_burst | 59.1 | 69.1 | 74.4 | 1.17 | 1.26 | +5.3 |

The §8.2 "1.25–1.29×" is the **FFI** backend; it splits into a genuine FFI/adapter cost
(+5–7 µs/event) and the pure kernel gap (native/cpp ≈ 1.13–1.17×). The FFI cost is the
`geometry_msgs → AwEkf* → plain-struct` double copy per call plus the boundary — it is real
and was previously (mis)attributed entirely to "kernel".

**Exp 2 — codegen ceiling (native-Rust µs/event; C++ is `-O3 -DNDEBUG`, no `-march`, so Eigen
is SSE2 — same ISA as default Rust).**

| config | realdata | straight | queue_burst | vs C++ |
|---|---|---|---|---|
| C++ (ref) | 55.9 | 57.4 | 59.1 | 1.00 |
| baseline (release, overflow-checks=on, SSE2) | 66.5 | 65.4 | 69.0 | 1.15–1.19 |
| overflow-checks=off (SSE2) | 58.9 | 58.9 | 64.6 | **1.03–1.09** |
| lto=fat + cgu=1 + ovf-off (SSE2) | 59.5 | 59.4 | 65.6 | 1.03–1.11 |
| target-cpu=native only (AVX, ovf on) | 55.9 | 56.4 | 57.9 | 0.98–1.01 |
| perf-all (AVX + lto + cgu=1 + ovf-off) | 45.6 | 45.8 | 49.2 | **0.81–0.83** |

`overflow-checks` is the dominant **ISA-neutral** factor (~7.6 µs/event). LTO/cgu add
essentially nothing (the crates are small and nalgebra is already inlined). ISA-matched, with
overflow-checks off, the Rust kernel is within **1.03–1.09×** of Eigen. `target-cpu=native`
(AVX+FMA the C++ build does not use) closes the rest and, combined, makes Rust **0.81–0.83× —
faster than C++** — but that is an ISA lever available to both languages, not part of the
like-for-like gap.

**Exp 3 — per-op microbench (ns/iter, fixed 300-dim state; synthetic P is denser than the
replay steady state, so absolute per-op gaps are upper bounds — used to localize, not to size,
the gap).**

| op | C++ SSE2 | C++ AVX | Rust base (SSE2,ovf) | Rust ovf-off SSE2 | Rust perf AVX |
|---|---|---|---|---|---|
| predictWithDelay | 43 639 | 39 163 | 53 610 | **28 167** | 27 752 |
| updateWithDelay m=3 | 64 477 | 36 908 | 86 804 | 87 754 | 76 837 |
| updateWithDelay m=2 | 53 604 | 29 378 | 63 613 | 66 031 | 59 028 |
| mahalanobis m=3 / m=2 | — | — | 40.7 / 24.3 | — | — |

- **predict** is memory-bound (the 294×294 P-block shift/copy) and its Rust slowdown is
  **100 % overflow-checks**: with the flag off it is 28.2 µs — *faster* than Eigen (43.6 µs).
  The index/offset arithmetic in the block copy is where the checks land.
- **update** is FLOP-bound and **unaffected** by overflow-checks or LTO/cgu (87.8/66.0 ≈
  baseline). The ISA-matched gap (Rust SSE2 1.35×/1.19× over C++ SSE2) is the genuine kernel
  residual (H3), and it *widens* under AVX (C++ AVX 36.9/29.4 vs Rust AVX 76.8/59.0 → 2.0×):
  Eigen vectorizes the rank-m covariance downdate far better.
- mahalanobis is negligible (tens of ns) — not a factor.

**Exp 4 — FLOP-structure audit (H4).** `time_delay_kalman_filter.cpp` vs the Rust port compute
the **identical** products and block-structure exploitation: predict = {A·P00·Aᵀ+Q, A·P0j
(6×294), P·Aᵀ (294×6), copy P (294×294), state slide}; update = {e=y−C·x_d, S=C·P_dd·Cᵀ+R,
P_CT=P_*d·Cᵀ (300×m), LLT-solved Kᵀ, x+=K·e, **P −= P_CT·Kᵀ (300×300 rank-m downdate)**}. Same
asymptotic work; Rust only materializes two tiny transposes (6×6, 6×m) Eigen keeps lazy
(negligible — predict is *faster* in Rust once overflow-checks is off). **No divergence.**

**Exp 5 — kernel identity (H3).** The dominant op both sides is the 300×300 **rank-m** (m=2/3)
covariance downdate. `matrixmultiply` is **absent** from the dependency tree (Cargo.lock: the
crates are `no_std` and never enable it); even in the std FFI build, nalgebra's `gemm_uninit`
only dispatches to `matrixmultiply::dgemm` when every dimension `> SMALL_DIM = 5`, and the
contraction dimension here is m = 2/3 — so the downdate **always** runs nalgebra's naive
per-output-column `gemv` loop (no register blocking, no accumulator reuse across the m rank-1
updates). Eigen runs its own blocked/vectorized kernel. `objdump` confirms both reach AVX+FMA
(`%ymm`/`vfmadd`) under the aggressive flags — so H3 is microkernel **quality**, not SIMD
width.

**Root-cause breakdown of the shipping FFI 1.26× (per-event excess over C++, replay ground
truth; shares vary with the scenario's predict/pose/twist mix):**

| cause | hypothesis | mechanism | share of the excess | evidence |
|---|---|---|---|---|
| overflow-checks | H1 | integer index/offset checks in the predict block-copy path | **29–44 %** (~4.5–6.6 µs) | Exp2 (baseline−ovf-off), Exp3 predict halves |
| FFI / adapter marshaling | H2 | `geometry_msgs↔AwEkf↔plain` double copy + boundary per call | **35–48 %** (~5–7 µs) | Exp1 (ffi−native) |
| nalgebra naive rank-m gemm | H3 | 300×300 downdate falls to per-column gemv (K≤5<SMALL_DIM; matrixmultiply absent) | **10–36 %** (~1.5–5.5 µs) | Exp2 (ovf-off native−cpp), Exp3 update, Exp5 |
| FLOP asymmetry | H4 | — none — same products/blocks both sides | 0 % | Exp4 |
| LTO / codegen-units | H1 | crates already inlined | ~0 % | Exp2 (lto+cgu ≈ ovf-off) |

(target-cpu/AVX is an orthogonal ~18 % lever for *both* languages, not counted in the
like-for-like gap; the C++ build does not use `-march` either.)

**Cheap improvement candidates (NOT implemented — each noted with its tradeoff):**

1. **overflow-checks=off in a dedicated release profile** — largest ISA-neutral win (~7 µs/
   event, halves predict). *Tradeoff/policy*: CLAUDE.md + rust-hardening mandate
   `overflow-checks=true` in every profile as the runtime backstop. All EKF integer arithmetic
   already uses `checked_*`/`saturating_*` (float math dominates), so the backstop is
   near-redundant here — but flipping it is a **policy exception requiring an explicit audit**,
   not a silent change.
2. **`target-cpu` / `-march` (e.g. `x86-64-v3`) on the deployment target, applied to BOTH the
   Rust crate and the C++ colcon build** — ~18 % each (AVX+FMA). *Tradeoff*: binary portability
   (won't run on older CPUs); must be matched on both sides for a fair comparison.
3. **Coarser FFI boundary** — one handle call per tick (batch predict + queue drain) and pass
   measurements as POD without the `geometry_msgs→AwEkf→plain` double copy. Recovers most of the
   ~5–7 µs FFI cost. *Tradeoff*: widens the C ABI surface; modest.
4. **Symmetric / blocked rank-m covariance downdate** (exploit P symmetry → ~half the FLOPs, and
   block the m rank-1 updates with FMA accumulator reuse) to beat nalgebra's naive gemv.
   *Tradeoff*: changes the arithmetic/rounding → **breaks the byte-identical conformance and
   needs a re-freeze under the §3 numeric contract**; not "cheap".
5. **LTO/cgu**: measured negligible here — not worth the compile-time cost.

Net: the shipping 1.26× is roughly (overflow-checks ≈ FFI-marshaling) > (nalgebra kernel), with
**no FLOP divergence**; the ISA-matched, overflow-checks-off Rust kernel is within ~1.05× of
Eigen, and full codegen flags make it faster.


### 8.4 FFI-coarsening investigation — negative result (2026-07-29)

Following §8.3 (FFI marshaling ≈ 35–48 % of the per-event excess), a plan tried to recover it
by coarsening the C ABI (batched getters + collapsed update crossings). Implemented, gated,
then **reverted** — no code shipped. Findings:

- **B1 audit (measurement-update path):** the adapter's `measurement_update_pose` /
  `measurement_update_twist` each make **exactly one** FFI crossing. `find_closest_delay_time_index`
  and `compensate_rph_with_delay` are performed *internally* by the Rust `EkfModule`, not
  re-crossed — so there are **no nested crossings to collapse**. (The standalone
  `find_closest`/`compensate_rph` FFI entries exist only for `test/test_ekf_module.cpp`.)

- **Getter batching (C) measured NET-NEGATIVE.** A batched `aw_ekf_module_get_outputs` (one
  crossing filling all six outputs) replaced the timer-callback's four individual getter
  crossings. Direct microbench of the node output path (`taskset -c 2`, N=10, static-lib link):
  the per-getter **FFI crossing overhead is only ~2–3 ns** — not a bottleneck. The getter
  **work** dominates (~220 ns for all six). Because `get_outputs` computes all six while the
  timer block consumes only four and the publish path still recomputes
  `pose_cov`/`twist_cov`/`yaw_bias`, `twist_cov` and `yaw_bias` end up computed twice
  (7 getter-works → 9): **305 → 375 ns/tick, a ~70 ns/tick regression** (absolute scale
  negligible — 3.5 µs/s at 50 Hz — but the wrong direction). The §8.1 replay harness is blind
  to this path (`ekf_replay` never calls the getters), confirming the getters were never in the
  §8.3 FFI number.

- **Where the §8.3 "FFI marshaling 5–7 µs/event" actually is:** the **measurement-update**
  path (`ffi − native` on the replay, which drives predict/update, not getters). It is
  dominated by the C++-side `geometry_msgs` construction + adapter `geometry_msgs→AwEkf→plain`
  marshaling of the 36-element covariances — partly inherent to keeping the node a thin C++
  shell over ROS messages. A borrow-instead-of-copy on the Rust entry (B2) would save only the
  ~44-double `pose_from_ffi` copy (~tens of ns), not the C++-side work.

**Conclusion:** the FFI boundary is **not a worthwhile perf lever** for the EKF — crossings are
~ns, the measurement-update marshaling cost is largely inherent to the thin-shell design, and
batching the getters regresses. No code change shipped; the reduction opportunity identified in
§8.3 is therefore **overflow-checks and codegen flags (§8.5)**, not FFI coarsening.

### 8.5 Corrected attribution + nalgebra overflow-checks recovery (2026-07-29)

§8.3 identified overflow-checks as ~half the FFI-backend excess over C++ and located it in the
"predict block-copy index arithmetic". Refined finding: that tax lives in **nalgebra's**
internal `copy_from`/`gemm`/`axpy` loops (bounded loop-counter/index arithmetic that cannot
overflow in practice), **not** in our crates' arithmetic (which already uses `checked_*`). It is
therefore removable with a **per-package profile override** — `overflow-checks = false` for
`nalgebra` only — applied in both `realtime_core/Cargo.toml` and the vendored FFI crate's
`Cargo.toml` (the profile Corrosion compiles the static lib with). Every `realtime_*` crate
keeps `overflow-checks = true` (the profile default), so our own integer arithmetic still fails
loudly.

**Invariance:** `overflow-checks` guards only integer ops, so float results are unchanged — the
frozen 13-scenario conformance traces are **byte-identical to the pre-change build**, both
native (`ekf_replay` Rust example) and through the FFI backend, and all decisions match the
frozen C++ fixtures 100 %. Workspace tests 178/178 (release + debug); colcon
`EKF_USE_RUST=ON` 152/152, `OFF` unaffected. Our crates staying checked is structural: no
`realtime_*` package override exists, so they inherit the checked default.

**Attribution (trace-off native, §8.1 conditions, µs/event):**

| build | realdata | note |
|---|---|---|
| native, overflow-checks ON everywhere (§8.3 baseline) | 66.5 | — |
| native, **nalgebra override only** | 60.6 | recovers **5.9 µs (~79 % of the tax)** |
| native, overflow-checks OFF everywhere (§8.3 ceiling) | 58.9 | recovers 7.6 µs (100 %) |
| C++ (`-O3`, SSE2) | 54.8 | reference |

So ~79 % of the overflow-checks tax is inside nalgebra (removed safely) and ~21 % is in our
still-checked code — a deliberate safety/perf split, not a blanket flag flip.

**Before/after — shipping FFI-Rust backend (trace-off, taskset -c 2, N=10, parse-baseline
subtracted):**

| scenario | C++ | FFI before (ovf ON) | FFI after (nalgebra ovf off) | ffi/cpp before → after | recovery |
|---|---|---|---|---|---|
| realdata | 54.8 | 70.8 | 59.7 | 1.27 → **1.09** | −11.1 µs |
| straight | 57.0 | 72.3 | 60.2 | 1.26 → **1.06** | −12.1 µs |
| queue_burst | 61.1 | 74.4 | 66.8 | 1.26 → **1.09** | −7.6 µs |

The shipping Rust EKF backend now runs within **1.06–1.09×** of the header-only, fully-inlined
C++/Eigen backend (down from 1.26×), with no numeric change and our crates' overflow safety
intact. The residual ~1.06–1.09× is the ISA-matched nalgebra-vs-Eigen kernel gap (§8.3 H3, the
naive rank-m covariance downdate) plus the inherent FFI/`geometry_msgs` marshaling (§8.4);
closing further would need either a hand-blocked downdate kernel (breaks byte-identity → re-freeze)
or `-march`/target-cpu on both backends — out of scope here.
