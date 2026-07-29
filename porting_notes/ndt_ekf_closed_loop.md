# All-Rust localization core in the closed loop — NDT+EKF vs all-C++

Integration test: the localization core built entirely in Rust
(`NDT_USE_RUST=ON` + `EKF_USE_RUST=ON`, profile `rust_all`) vs entirely in C++
(`cpp`), driven through the production-like GNSS-reinitialization stack replay
(2026-07-29). Each engine (NDT align, EKF) was already proven behavior-equivalent
in isolation by the frozen open-loop conformance (byte-identical traces) and unit
tests; this is the **system-level** integration check of running both Rust ports
together in the closed loop.

## Setup

- İstanbul 57-minute loc bag (34,375 clouds @10 Hz + twist + GNSS), tiled map with
  150 m differential loading, CFS, 4 workers/engine (OpenMP / Rayon), governor
  performance @3.2 GHz, one shared frozen initial pose, GNSS-reinit watchdog
  (starvation 25 s, motion-compensated).
- Run order `cpp1 → rust1 → rust2 → cpp2` (interleaved for repeat/cross bands),
  `REINIT=1`, `OUT_DIR=stack_replay_results_ndtekf`.
- **Route is deliberately LiDAR-hostile** (Eurasia sub-sea tunnel, long bridges,
  urban canyons); all rates are stress-route values, not nominal-ODD.
- Provenance: realtime_core `421a127` (both NDT + EKF Rust), fork `9eb44083`,
  paper `5d4f566`; bag sha `eb80d649…`, map-meta sha `c135eee3…`.
- (Ops note: a first batch had `cpp1` complete but `rust1` externally killed by a
  stray process-group termination; the runs were re-executed cleanly as a single
  pipeline. `cpp1` here is from the first batch, the other three from the re-run;
  governor/pin identical across both.)

## Per-run results (57 min each)

| run | profile | coverage% | align frames | NDT cap% | iter median | re-inits (all ok) | NDT exe max (ms) | >100 ms | EKF Hz | EKF gap max (ms) | peak RSS (MiB) | map loss |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cpp1 | all-C++ | 84.1 | 30,992 | 20.3 | 14 | 12 | 142.7 | 2 | 50.0 | 30.0 | 1424 | 0 |
| cpp2 | all-C++ | 85.3 | 32,277 | 25.8 | 14 | 9 | 124.2 | 2 | 50.0 | 30.0 | 1730 | 0 |
| rust1 | all-Rust | 93.9 | 33,470 | 13.2 | 14 | 3 | 25.4 | 0 | 50.0 | 30.0 | 1888 | 0 |
| rust2 | all-Rust | 92.7 | 33,035 | 12.1 | 14 | 3 | 25.0 | 0 | 50.0 | 30.0 | 1860 | 0 |

Coverage = share of the run with an accepted NDT pose within a 3 s gap; cap% over
aligned frames (`iteration_num` ≥ 30); the C++ >100 ms frames are all inside
re-initialization windows (TPE contends with the main callback); no map tile was
ever unloaded by a divergent estimate; all 27 re-initializations across the four
runs succeeded.

## Shared failure geography (route-driven, not implementation-driven)

Starvation episodes (sim-seconds from run start):

- cpp1: 1181, 1477, 1572, 1707, 1923, 1955, 1992, 2027, 2336, 2431, 3304, 3357
- cpp2: 1399, 1594, 1630, 1688, 1725, 1761, 1919, 2371, 2408
- rust1: 1286, 2346, 3206
- rust2: 1171, 2401, 3395

All four runs starve at the same two hardest sections (≈1200 s tunnel approach and
≈2380 s), independent of engine — the failures are route-driven. The C++ runs add
many further episodes in the 1450–2030 s band that neither Rust run hits.

## Verdict: engine bands are disjoint (systematic, faster Rust core → healthier loop)

Same-engine repeat spreads are narrow and the engine bands do **not** overlap:

| metric | all-C++ (cpp1,cpp2) | all-Rust (rust1,rust2) |
|---|---|---|
| coverage% | 84.1–85.3 | 92.7–93.9 |
| NDT cap% | 20.3–25.8 | 12.1–13.2 |
| re-inits | 9–12 | 3 |
| NDT exe max (ms) | 124–143 | 25 |
| >100 ms frames | 2/run (recovery windows) | 0 |

Cross-language EKF gate / innovation differences (quality-gate disagreements
8,218–9,289; innovation p99 1.73–1.89 m) exceed the same-engine repeat bands
(cpp repeat 7,089 / 1.95 m; rust repeat 4,566 / 1.04 m), consistent with that
systematic difference rather than replay noise.

This is **not** "behaviorally identical within the repeat band" — it is a
consistent advantage: the roughly-halved align cost of the Rust core (exe max
25 ms vs ~130 ms) lets it ride out transient match-quality degradations that push
the slower C++ core past the starvation threshold, so it re-initializes 3× versus
9–12× and holds ~9 points more accepted-output coverage. The NDT iteration median
is identical (14) for all runs — where localization is healthy the two cores do the
same work (as the frozen conformance proves); the difference is *how often* the loop
stays healthy. Memory is comparable, Rust ~130–460 MiB higher (preallocated scratch
and the arc-swap map double-buffer), well within the guard.

## Relationship to the frozen `stack_replay.json`

The paper's frozen stack replay varied **NDT only** (EKF always C++): cpp coverage
82.3–83.2%, rust 93.5–96.5%. This all-Rust-vs-all-C++ run reproduces the same
picture (cpp 84.1–85.3%, rust 92.7–93.9%), which corroborates that **NDT align cost
dominates closed-loop health**; adding the Rust EKF (cheap, ~8 µs/tick) does not
move the bands. The paper result therefore already captures the effect; this run is
a confirmation that the full Rust core integrates and behaves consistently, not a
new headline for the paper.

## Limitations

Two runs per engine; no ground truth (pose deltas measure substitutability, not
error); closed-loop feedback is chaotic, so only run-level bands are claimed; the
all-Rust-vs-all-C++ contrast combines the NDT and EKF ports (each separately
conformance-verified); stress route, not nominal ODD. Raw run tree
`stack_replay_results_ndtekf/` is not committed (large); SHAs and commits above pin
the provenance.
