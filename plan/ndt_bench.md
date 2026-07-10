# Benchmarking `autoware_ndt_scan_matcher` — C++ vs Rust — Roadmap

## Goal

Measure the performance of the two interchangeable NDT engines **fairly and reproducibly**. The package
runs one ROS node over either engine via the `NDT_USE_RUST` CMake option (OFF = legacy C++/PCL + Eigen,
ON = the Rust port over a C ABI; the Rust engine additionally has `std` / `no_std` single-core / `no_std`
`mt` build configs). Behavior equivalence is already owned by the differential tests — **this roadmap is
about speed, not correctness.**

Scope: per-frame latency + throughput, the WCET tail, iteration counts, and allocation behavior. The one
honest comparison axis is `NDT_USE_RUST` OFF vs ON: **same node, same ROS graph, same input, same output
path — only the engine differs.** ON measures the shipping Rust-over-FFI configuration (the ingest FFI is
part of the number).

Non-goals: correctness (the `standard_sequence_*` + unit differential tests are the oracle); algorithm
tuning; a fully automated CI perf-gate (noted as a possible follow-on). No benchmark code is written by
this document — it lays out the work.

## Principle: capture-once, replay-everywhere

The load-bearing idea. Instrument **one** sensor callback (either backend) to dump, per frame:

1. the post-ingest **base_link source cloud** (`[f32; 3]` flat array — already computed by
   `src/sensor_points.rs` `_prepare` / the legacy `transform_sensor_measurement`),
2. the **active map** (PCD path + voxel resolution, or the tile clouds),
3. the **initial guess** pose,
4. the **params** (`resolution` / `max_iterations` / `outlier_ratio` / `num_threads`).

Serialize these as **versioned fixtures**. Then L2 and L3 feed *identical bytes* to both engines, and L1
uses the source rosbag/sequence they were captured from. Because the differential tests already prove the
two engines produce the same poses, identical inputs guarantee **identical work** — so the only variable
left is time. This also removes ROS timing jitter from L2/L3 and makes iteration-count and tail-latency
distributions cross-language-identical.

Capture granularity by level: **post-ingest** cloud for the align-kernel benches (L2 align, L3), the
**raw `PointCloud2` buffer** for the ingest micro-bench (L2 ingest).

## Data tiers

| Tier | Content | Strength | Weakness | Use |
|---|---|---|---|---|
| **Real** | Autoware `sample-rosbag` (recorded real LiDAR `/sensor_points`) + **`sample-map-rosbag`** (real PCD; the map paired with the bag in the rosbag-replay demo — *not* `sample-map-planning`, which is the planning-sim map) | Real point counts (~10⁴–10⁵) and real scene geometry ⇒ realistic convergence / iteration profile | Large (~193 MB bag), downloaded out-of-repo on demand (see [Sample-data provisioning](#sample-data-provisioning-download-if-absent)) | L1b headline number; the source for capturing L2/L3 fixtures |
| **Built-in synthetic** | `make_sample_half_cubic_pcd()` (`test/test_util.hpp:26`) — ~30,603 pts, 3 orthogonal planes; drives `standard_sequence_for_initial_pose_estimation` | Deterministic, self-contained (no download), already wired | 3 flat planes ≠ real streets ⇒ unrepresentative convergence/cost distribution | Deterministic CI perf-regression + cross-language parity smoke — **not** the headline number |
| **Captured fixtures** | N representative frames (map + source + guess + params) dumped from a real run | Real sizes/geometry + deterministic + identical bytes to both engines | One-time capture step | The L2 / L3 workhorse |

"Real" means **recorded real-sensor data**, not live measurement — benchmarks always replay a recorded
bag (from the Autoware sample or your own vehicle logs), never a moving vehicle. Own-vehicle logs +
production map are most representative of a specific deployment; the Autoware sample is the reproducible
public baseline.

## L1 — node / end-to-end (primary; lowest effort, ships first)

**No node instrumentation is needed** — the per-frame end-to-end timer already exists on **both**
paths, identically: the `execution_time` diagnostic key + the `exe_time_ms`
(`autoware_internal_debug_msgs/Float32Stamped`) publisher, measured `exe_start`(callback top) →
`exe_end`(after align + covariance) via `std::chrono::system_clock` µs→ms. Legacy C++:
`src/ndt_scan_matcher_core.cpp` (`exe_time_pub_` :138, `exe_start` :305, `exe_end` /
`add_key_value("execution_time")` / publish :603–617). Rust path:
`rust/src/ndt_scan_matcher_sensor_rust.cpp:96/119-130`. This span (ingest + align + covariance +
convergence) is exactly the end-to-end cost that matters. `iteration_num` is also a diagnostic key on
both paths (`src/ndt_scan_matcher_core.cpp:466`).

The honest comparison axis is `NDT_USE_RUST` **OFF vs ON**: same node, same ROS graph, same input —
only the engine differs (ON includes the ingest FFI, i.e. the shipping config). Because it is a CMake
source-set switch (not a runtime flag), OFF/ON is a **rebuild between two passes**, replaying the
**same** input each time; the differential tests guarantee same poses ⇒ identical work ⇒ time is the
only variable.

Common analysis (both tiers): report **distributions** (p50 / p95 / p99 / max), not means — align
iteration count varies per frame, so the tail is the story. **Overlay `iteration_num`** so a latency
delta caused by different convergence is separated from raw per-iteration cost. Record via a small
subscriber (or `ros2 topic`/`ros2 bag`) on `exe_time_ms` + `/diagnostics` → CSV, fed to
`bench/gen_report.py`.

### L1a — deterministic, in-repo (ships first; CI regression gate) — IMPLEMENTED

Drives the full node **in-process**, reusing the integration-test fixture (`test/test_fixture.hpp` +
`StubPcdLoader`/`StubTriggerNodeClient`/`StubSensorPcdPublisher`) plus a new
`test/stub_ekf_pose_publisher.hpp`: the standard `standard_sequence` test only exercises the
align-service/TPE path, so reaching the per-frame `callback_sensor_points` (which publishes
`exe_time_ms`) additionally needs activation + an `ekf_pose_with_covariance` stream bracketing each
sensor stamp + the map loaded via the stub. The bench `test/bench/l1a_node_frame_bench.cpp` primes the
map, then replays the synthetic `make_default_sensor_pcd()` cloud frame-by-frame (serialized by waiting
for each `exe_time_ms`), guessing 0.5 m off the tile so the align does representative work, and writes a
per-engine JSON. Built only under `option(NDT_BUILD_BENCH_L1)` (OFF by default ⇒ excluded from
`./test.sh`/`colcon test`), for **both** engines. `bench/run_l1a.sh [ITERS] [WARMUP]` does the
`NDT_USE_RUST` OFF/ON two-pass, asserts the OFF/ON `iteration_num` match (fairness), merges, and renders
via `gen_report.py` (`bench/run.sh` env conventions: `OUT_DIR`/`TASKSET`/`WS_ROOT`). **Download-free and
deterministic** → the OFF-vs-ON regression baseline. Its synthetic 3-plane geometry is unrepresentative,
so it is **not** the headline number. (Smoke result on the dev container: both engines converge in 10
iterations; node-level p50 ≈ 34 ms C++ vs ≈ 13 ms Rust — indicative only, regenerate locally.)

### L1b — real data (headline; opt-in) — ✅ CONVERGED (2026-07-10, urban dataset)

**Headline (İstanbul urban localization dataset, loc-only bag; both engines `iteration_num = 3`,
120 s each @ 10 Hz, `num_threads = 1`, CycloneDDS):** node `exe_time_ms` — C++ p50 4.20 / p95 6.45 /
max 11.97 ms vs **Rust p50 3.61 / p95 5.68 / max 7.70 ms → ≈1.16× at p50, ≈1.56× at max**. Real urban
frames converge in 3 iterations, so the align kernel is a smaller share of the frame than in L1a/L3
(hence the smaller ratio); the tail improves the most. Results in `bench/l1b.json` + `l1b_report.html`.

**Dataset switch:** the original 2021 `sample-rosbag` is raw sensor data (Velodyne packets, no
PointCloud2/TF) needing the full sensing stack; the Autoware **urban-environment localization
evaluation** dataset's *localization-only* bag instead contains the preprocessed
`/localization/util/downsample/pointcloud` (PointCloud2) + `/localization/twist_estimator/...`
(twist) + GNSS map pose + `/tf_static` directly — so the graph collapses to map loader + NDT/EKF loop
(`launch/ndt_l1b_loc.launch.xml`). Data via gdown (see the eval docs page).

**Replay shims required (all scripted in `bench/`):**
- `l1b_restamp_relay.py` — the bag's cloud/twist **header stamps lag its `/clock` by ~27 days**;
  without re-stamping, NDT's pose interpolation fails and the EKF rejects the twist (freezing at the
  init pose). The relay rewrites `header.stamp := sim-now` for both.
- Replay with `--topics ...` (exclude the recorded `/clock`) so the player's `--clock` is the **single
  time base** (two clock publishers otherwise flip-flop sim time and thrash the TF buffer).
- **Map crop ±3.5 km** (`pointcloud_map_crop35.pcd`): the single-file 15 km PCD at 2 m resolution
  overflows `MultiVoxelGridCovariance`'s **int32 voxel index** (`Leaf size is too small ... Integer
  indices would overflow`) → the engine target stays **empty** and every score is 0 (±5 km = 2.148e9
  voxels still overflows by 0.05%!). The production tile pipeline avoids this by construction.
- Init (`l1b_ndt_align_init.py`): fresh GNSS seed → **pause the bag** (else the multi-second TPE
  leaves the pose ~50 m stale at 13 m/s) → `ndt_align_srv` → publish refined pose on `/initialpose3d`
  → SetBool triggers → resume. The `pose_initializer` itself never becomes ready on this replay, and
  the `ros2 service call` CLI is broken in this image — both bypassed via rclpy.

Original status notes (2026-07-10, before the dataset switch):

**Status (2026-07-10).** The full sensing stack needed to replay the `sample-rosbag` was built and the
localization graph was validated end-to-end short of a converged headline. The bag is **raw sensor
data** (LiDAR = `velodyne_msgs/VelodyneScan` packets ×3, raw ublox GNSS, **no `/tf`, no PointCloud2**),
so NDT input requires the Autoware sensing pipeline. What was installed/built in this `src/core`-only
workspace: `ros-humble-rosbag2*` + `ros2cli`/`ros2launch` (the image lacked `ros2 bag`/`ros2 launch`),
then Nebula, `autoware_pointcloud_preprocessor`, `sample_sensor_kit_launch` (+ `common_sensor_launch`,
descriptions), `sample_vehicle_launch`/`sample_vehicle_description`, `tier4_vehicle_launch`
(robot_state_publisher TF), and `autoware_global_parameter_loader` — ~108 packages via
`--packages-up-to`. `launch/ndt_l1b_bench.launch.xml` composes vehicle TF + `sensing.launch.xml`
(`launch_driver:=false` → Nebula decodes the bag packets) pushed under the `sensing` namespace + the
core map + `autoware_core_localization` (voxel→NDT→EKF→pose_initializer), `use_sim_time:=true`.

**Verified live:** the 50-node graph comes up, Nebula decodes the 2021 velodyne packets into clouds,
the top-LiDAR cloud → voxel downsample feeds NDT's `points_raw` at ~**28 Hz**, and the map service,
GNSS map-frame pose, and robot_state_publisher TF are all present. **Not obtained:** a converged
OFF-vs-ON `exe_time_ms` headline — the localization init/activation handshake (pose_initializer →
`ndt_align_srv` → trigger) did not complete in this container, compounded by FastDDS shared-memory
transport instability (`open_and_lock_file failed`, `rcl context invalid` on CLI service calls) after
the repeated build/launch/kill churn, and the 30 s bag window. This is an **environment** limitation
(a build-focused container with a churned DDS state), not a defect in the launch or the NDT node.
`bench/run_l1b.sh` encodes the whole pipeline (UDP-only DDS + `/dev/shm` hygiene + single-pass
`--clock` + GNSS-derived `initial_pose` + record) and is expected to reproduce the headline on a
**fresh full-Autoware container**; the L1a number remains the working, in-repo OFF-vs-ON headline.

Original scaffold notes:

Launch the node and `ros2 bag play` the Autoware `sample-rosbag` against `sample-map-rosbag`, logging
`exe_time_ms` + `iteration_num`. Real point counts / scene geometry give the realistic convergence +
tail-latency profile. Opt-in (needs the ~193 MB bag), provisioned on demand (below). **Scaffold
landed** (`bench/fetch_sample_data.sh`, `bench/record_exe_time.py`, `launch/ndt_l1b_bench.launch.xml`
composing `autoware_pointcloud_map_loader` + downsample + the NDT node, and `bench/run_l1b.sh` doing
fetch → preflight → OFF/ON two-pass → bag replay → record → merge/report). Producing a **converged
headline is best-effort**: it additionally needs TF (`map→base_link`) + an `ekf_pose_with_covariance`
stream (`autoware_ekf_localizer` + `autoware_pose_initializer`) + the bag's actual LiDAR topic
(`BAG_LIDAR_TOPIC`, via `ros2 bag info`) — supplied from the bag or by extending the launch; the runner
preflights these and warns/records-zero if missing rather than fabricating a number.

Inputs: **`sample-rosbag` + `sample-map-rosbag`** for the L1b headline; `standard_sequence` (synthetic)
for the L1a deterministic CI baseline.

### Sample-data provisioning (download-if-absent)

The sample bag/map are fetched **only when absent**, by the opt-in bench runner — **never** from the
default `colcon test` / `./test.sh` gate (those stay hermetic and offline; a ~193 MB fetch there would
be flaky, slow, and blocked by CI egress). This mirrors the L3 precedent (`NDT_BUILD_BENCH=OFF` +
`bench/run.sh`).

- **Cache location** = the standard Autoware layout, so a machine already provisioned by the
  `demo_artifacts` ansible role is a cache hit: `~/autoware_data/recordings/bags/sample-rosbag` and
  `~/autoware_data/maps/sample-map-rosbag` (env-overridable, e.g. `AUTOWARE_DATA_DIR`).
- **Must-haves**: verify SHA256 **even on a cache hit** (guards a truncated 193 MB file); download to a
  temp path → verify → atomic `mv` into place; resumable (`curl -C -`); **offline + absent ⇒ skip or
  fail with the URL + checksum printed**, never hang.
- **Pinned source** (single source of truth: `autoware/ansible/roles/demo_artifacts/tasks/main.yaml`):

  | Artifact | URL | Size | SHA256 |
  |---|---|---|---|
  | `sample-rosbag.zip` | `https://autoware-files.s3.us-west-2.amazonaws.com/recordings/bags/demos/sample-rosbag.zip` | ~193 MB | `5f9d36353393b3d249212153c19049822b1298db56512aa045b4f7f6fc37cf88` |
  | `sample-map-rosbag.zip` | `https://autoware-files.s3.us-west-2.amazonaws.com/maps/demos/sample-map-rosbag.zip` | ~2 MB | `07e2da0b0bf12e2324f7083c2ce5556fb8044c50cef1da6428ab9084c3903bc8` |

- **Runner shape**: `bench/fetch_sample_data.sh` (an `ensure <url> <sha256> <dest>` helper) +
  `bench/run_l1.sh` (ensure-data → build OFF → play/record → rebuild ON → replay/record →
  `gen_report.py`), following `bench/run.sh`'s env conventions (`OUT_DIR` / `TASKSET` / `WS_ROOT`).

## L2 — kernel micro-benchmark (locate where time goes)

Rust side: add `autoware_ndt_scan_matcher_rs/benches/` with **`criterion`** (dev-dependency; the crate has
**no `benches/` yet**). Bench targets:
- `ndt::align` (`src/ndt.rs:610`) — the optimization loop, the dominant cost.
- ingest `_prepare` (`src/sensor_points.rs`) — the decode + sensor→base_link transform pass (raw
  `PointCloud2` fixture input).
- `compute_derivatives` **serial vs `parallel`** (rayon) — the per-point reduction, at matched thread
  counts.

C++ side: a google-benchmark target, or a minimal `std::chrono::steady_clock` harness, over
`multigrid_ndt_omp` align on the same fixtures.

Inputs: 2–3 frozen fixtures spanning ~10k / ~30k / ~100k points (+ their maps/voxel grids), captured from
real data; plus a **synthetic N-sweep** (vary point count) to characterize per-point scaling and cache
effects. Both languages load the identical fixture files.

## L3 — offline differential replay (realistic distributions, zero jitter)

Replay the **full captured frame stream** (map snapshot + source + guess per frame) through both engines
offline with a **monotonic clock**, collecting per-align latency and iteration-count distributions. Inputs
are cross-language-identical by construction. Reuse the L2 fixture loader; implement as a Rust binary /
example on the Rust side and a small C++ replay harness on the C++ side. This is what makes tail latency
and iteration profiles reflect reality while staying deterministic and comparable.

## Fidelity controls & pitfalls (make the comparison fair)

- **`overflow-checks = true` in the Rust release profile** (`Cargo.toml`) adds integer-arithmetic checks
  C++ lacks. Measure the shipping config (checks on) as the primary number; optionally add a bench profile
  with checks off to separate "algorithmic parity" from "hardening cost" — and disclose which is which.
- **Parallel-backend parity**: set the same `num_threads` for Rust `parallel` (rayon) and C++ OpenMP;
  compare **serial-vs-serial** (the deterministic WCET baseline) *and* **parallel-vs-parallel** separately.
- **Identical map / resolution / initial guess** on both sides — build the map from the same PCD at the
  same voxel resolution, and use the captured per-frame guess (a different guess changes convergence and
  makes timing incomparable).
- **Monotonic clock for L2/L3** (Rust `Instant`, C++ `steady_clock`); the node's `execution_time` uses
  `system_clock`, fine for L1 relative A/B but not for micro timing.
- **Environment pinning**: Release build, CPU governor = performance, turbo/SMT disabled or documented,
  `taskset` to isolated cores, discard warmup frames, multiple trials.
- **Verify correctness parity first** — only compare engines that are producing the same poses.
- **`mt` note**: the sensor-ingest path is identical across the Rust `std` / `no_std` / `mt` builds, and
  the ROS node links the `std` build, so L1/L2/L3 numbers are backend-agnostic. `mt` is relevant only if
  the goal is to benchmark the multi-core lock path itself (in which case use `tests/concurrency.rs` /
  a multi-core replay under `--features mt,awkernel_sync/std`).

## Metrics & reporting

- Latency **distributions**: p50 / p95 / p99 / max (per frame at L1, per align at L2/L3). Means hide the
  RT-relevant tail.
- `iteration_num` per frame (separates convergence-count differences from per-iteration cost).
- **Allocation**: dhat / heaptrack; the Rust engine is alloc-free after warmup, guarded by
  `tests/zero_alloc.rs` — report allocations/frame for both engines.
- Tooling: `criterion` (statistical micro-bench), `perf stat` / `perf record` + flamegraph, google-benchmark
  (C++ micro), `ros2 bag` + a diagnostic/topic logger (L1).

## Phasing / milestones (each independently useful)

- **M1 — L1a on `standard_sequence`** (download-free): **DONE** — `test/bench/l1a_node_frame_bench.cpp`
  + `test/stub_ekf_pose_publisher.hpp` + `option(NDT_BUILD_BENCH_L1)` + `bench/run_l1a.sh`. Gives the
  OFF-vs-ON number and the CI-regression baseline.
- **M2 — L1b on real data**: **SCAFFOLD DONE** — `bench/fetch_sample_data.sh` (download-if-absent) +
  `bench/record_exe_time.py` + `launch/ndt_l1b_bench.launch.xml` + `bench/run_l1b.sh`. A converged
  headline on `sample-rosbag` + `sample-map-rosbag` is best-effort (needs TF + EKF initial-pose + the
  bag topic wired). Optionally add fixture-capture instrumentation here to seed L2/L3.
- **M3 — L2 micro-benches**: `benches/` (criterion) + the C++ kernel harness on the captured fixtures +
  synthetic N-sweep.
- **M4 — L3 replay**: the offline differential replay harness on the full captured stream.

## CMake / wiring precedent

A Rust bench or replay target follows the existing Corrosion + `add_test` pattern
(`CMakeLists.txt:186-194`, `autoware_ndt_scan_matcher_rs_cargo_test`). Keep benches out of the default
`colcon build` (opt-in, like the cargo-test CTest) so they don't slow normal builds.

L1b is an **opt-in runner** (`bench/run_l1.sh`), not a default ctest — a network fetch must never sit in
the default hermetic gate (`./test.sh`). If a "test runner" ergonomic is wanted, wire an **opt-in
labeled ctest** (`LABELS "benchmark"`, excluded from `./test.sh`, invoked via `ctest -L benchmark` or
behind `NDT_BUILD_BENCH`) that shells to the runner and returns the ctest **SKIP** code when the sample
data is absent and the host is offline — so it degrades cleanly instead of failing the suite.
