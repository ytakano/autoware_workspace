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

