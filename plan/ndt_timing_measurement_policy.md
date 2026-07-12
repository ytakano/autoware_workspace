# NDT Timing Measurement Policy

## Purpose

This document defines the timing-measurement policy for evaluating the Autoware NDT scan matcher and its Rust port.

The policy intentionally uses two measurement environments because they answer different questions:

1. **Production-representative measurement** evaluates behavior under the scheduling conditions used by Autoware in practice.
2. **Controlled engine measurement** isolates the NDT implementation from unrelated scheduler and system interference.

Do not mix conclusions from these two environments. Report them separately and state clearly what each result means.

---

## Measurement Profiles

### Profile A: Production-Representative Real-Data Replay

Use this profile for real-drive data and production-like replay.

#### Required configuration

- CPU frequency governor: `performance`
- CPU isolation: disabled
- Linux scheduler: normal Completely Fair Scheduler behavior
- Thread affinity: optional; use the production configuration unless the experiment explicitly studies pinning
- IRQ isolation: disabled unless the production deployment also isolates IRQs
- Other Autoware or system workloads: preserve the intended production-like environment

#### Goal

Measure the observed response-time distribution of NDT under realistic Linux scheduling and system interference.

These measurements include effects such as:

- scheduler preemption,
- competing ROS 2 nodes,
- interrupts,
- CPU migration,
- shared cache contention,
- memory-bandwidth contention.

These effects are part of the production environment and must not be treated as benchmark noise.

#### Report

At minimum, report:

- median,
- p90,
- p99,
- p99.9 when the sample count is sufficient,
- observed maximum,
- number and fraction of deadline overruns,
- source-point count,
- iteration count,
- relevant deterministic work counters,
- CPU utilization or system load when available,
- total number of frames,
- number of on-map and off-map frames.

For a 10 Hz pipeline, report the number of frames exceeding 100 ms.

#### Allowed interpretation

Use language such as:

- "production-representative observed response time",
- "observed maximum under the deployed CFS configuration",
- "deadline-overrun frequency in the measured run".

Do not describe these values as a certified WCET.

---

### Profile B: Controlled Engine Characterization

Use this profile for synthetic fixtures, counter-generated adversarial inputs, cross-language comparisons, unit-cost regression, scaling experiments, and allocator studies.

#### Required configuration

- CPU frequency governor: `performance`
- Benchmark thread pinned to one dedicated CPU
- Dedicated CPU isolated from general-purpose workloads
- Unrelated IRQs moved away from the benchmark CPU
- No background processes intentionally scheduled on the benchmark CPU
- SMT sibling disabled, isolated, or kept idle
- Stable thermal conditions
- Fixed compiler and linker settings
- Fixed allocator configuration
- Map construction and kd-tree construction excluded from the timed region unless the experiment explicitly studies them

Core isolation may be implemented with boot-time isolation, cpusets, or an equivalent mechanism. Record the exact mechanism.

#### Goal

Measure engine-intrinsic timing behavior while minimizing unrelated operating-system interference.

This profile is the primary environment for comparing:

- C++ and Rust implementations,
- frozen adversarial fixtures,
- deterministic work counters,
- per-operation timing models,
- source-size scaling,
- allocation behavior,
- warm-cache and cold-cache effects.

#### Required timed region

Time only the operation named by the experiment.

For align-kernel measurements:

1. load or construct the map before timing,
2. build the kd-tree before timing,
3. prepare all input buffers before timing,
4. begin timing immediately before `align`,
5. stop timing immediately after `align` returns,
6. validate the result outside the timed region when possible.

Do not silently include setup work in some runs and exclude it in others.

#### Report

At minimum, report:

- median,
- p99,
- observed maximum,
- sample count,
- warmup count,
- CPU model,
- kernel version,
- governor,
- isolation mechanism,
- affinity mask,
- IRQ configuration,
- SMT configuration,
- compiler versions and flags,
- fixture identifier and hash,
- binary or commit identifier,
- deterministic work counters,
- whether caches are warm or cold.

#### Allowed interpretation

Use language such as:

- "controlled engine latency",
- "isolated-core observed maximum",
- "implementation-level timing comparison",
- "time per unit of deterministic algorithmic work".

Do not claim that these values directly equal end-to-end Autoware response time.

---

## Bridge Experiment Between the Two Profiles

A small bridge experiment is mandatory. Its purpose is to quantify how much the production scheduling environment inflates or widens the controlled engine timing distribution.

Run the same frozen inputs under both profiles.

### Required bridge inputs

Include at least:

- the counter-guided union-worst fixture,
- the deployment-legal worst fixture,
- the deployment-legal oscillation fixture,
- the slowest real-data frame,
- one representative median-cost real-data frame.

### Required comparison

For each input and implementation, report:

- controlled-profile median and maximum,
- production-profile median and maximum,
- absolute difference,
- relative inflation,
- any deadline overrun introduced only in the production profile.

Use the following descriptive quantity:

```text
interference inflation =
    production-profile latency / controlled-profile latency
```

This ratio is descriptive only. Do not assume that scheduler and interference costs are additive or constant.

### Interpretation

The bridge experiment supports statements such as:

- the isolated measurement underestimates production-observed latency by a measured amount,
- scheduler and system interference widen the tail,
- implementation-level speedups persist or disappear under production scheduling.

It does not convert an isolated-core maximum into a hard system-level WCET.

---

## Cache Measurement Policy

Use separate series for warm-cache and cold-cache behavior.

### Warm-cache series

- Execute a fixed number of untimed warmup runs.
- Reuse the already-built map and kd-tree.
- Keep input buffers resident.
- Report the warmup count.

### Cold-cache series

- Use a documented cache-eviction method between samples.
- Do not rely on an undocumented sleep as a cache reset.
- Keep the eviction procedure outside the timed region.
- State that software cache eviction is an approximation unless hardware support provides stronger guarantees.

Never combine warm-cache and cold-cache samples into one distribution.

---

## Interference Sensitivity Experiment

For controlled fixtures, add an optional but recommended co-runner experiment.

Use a documented co-runner that stresses one resource at a time:

- LLC capacity,
- memory bandwidth,
- integer or floating-point execution units,
- interrupt pressure.

Run the benchmark on its dedicated CPU and place the co-runner on another CPU that shares the intended hardware resource.

Report each co-runner separately. Do not collapse different interference mechanisms into one unnamed "load" condition.

---

## Frequency and Thermal Control

Before every timing series:

1. set the governor to `performance`,
2. record the effective CPU frequency when possible,
3. confirm that the process is running on the intended CPU,
4. wait for the system to reach a stable thermal state,
5. record package temperature when available.

Abort or repeat a series when:

- thermal throttling occurs,
- CPU affinity changes unexpectedly,
- the governor is not active,
- another process occupies the dedicated CPU,
- the fixture or binary hash differs from the experiment manifest.

---

## Sample Counts

Use sample counts appropriate to the claim.

### Functional timing comparison

A minimum of 100 measured runs per frozen fixture may be used for preliminary implementation comparisons.

### Stable tail characterization

Use substantially more samples for tail claims. As a default target:

- at least 1,000 samples per fixture,
- repeated independent runs,
- preferably measurements collected across multiple sessions.

Do not perform extreme-tail extrapolation from a very small number of block maxima.

---

## pWCET and EVT Policy

Keep probabilistic timing analysis separate from ordinary percentile reporting.

### Controlled-profile data

EVT analysis, when retained, should primarily use controlled-profile measurements because the experimental conditions are easier to characterize.

The analysis must include:

- the fitting method,
- sample count,
- block size or threshold,
- independence and stationarity checks,
- confidence intervals,
- sensitivity to block size or threshold,
- a clear statement that the result is comparative unless all MBPTA assumptions are justified.

### Production-profile data

For CFS-based production measurements, prefer:

- empirical percentiles,
- observed maxima,
- deadline-overrun counts,
- time-series plots,
- scheduler and workload context.

Do not apply EVT mechanically to non-stationary production traces containing uncontrolled scheduler, IRQ, and workload effects.

---

## Cross-Language Fairness Requirements

Before comparing C++ and Rust timings for one input, verify that both implementations performed equivalent algorithmic work.

At minimum, compare:

- iteration count,
- derivative-pass count,
- total neighbor evaluations,
- total kd-tree node visits,
- line-search evaluation count when available.

Prefer a deterministic trace hash that includes per-pass work information.

If the work certificate differs:

1. mark the sample as a semantic or fidelity mismatch,
2. do not include it in direct timing-ratio claims,
3. preserve the input for debugging,
4. report the mismatch count separately.

Equal iteration count alone is not sufficient evidence of equal work.

---

## Reproducibility Manifest

Every experiment series must have a machine-readable or plain-text manifest containing:

```text
experiment_id
measurement_profile
run_timestamp
host_name
cpu_model
cpu_microcode
kernel_version
governor
isolated_cpus
benchmark_cpu
affinity_mask
irq_configuration
smt_configuration
memory_configuration
compiler_versions
compiler_flags
linker_flags
allocator
cpp_commit
rust_commit
fixture_id
fixture_hash
binary_hash
sample_count
warmup_count
cache_condition
co_runner
notes
```

Generate tables and plots from the recorded results rather than copying values manually into the paper.

---

## Recommended Execution Order

For each frozen fixture:

1. validate the fixture hash,
2. validate the binary and commit identifiers,
3. verify the CPU governor,
4. verify CPU affinity and isolation state,
5. verify IRQ placement,
6. perform warmups when required,
7. run the C++ and Rust measurements in an interleaved or randomized order,
8. capture deterministic work certificates,
9. reject unequal-work pairs from direct timing comparison,
10. save raw per-sample timings,
11. save system metadata,
12. generate summary statistics from the raw data.

Interleaving or randomizing implementation order reduces bias from temperature and long-term system drift.

---

## Required Result Separation

The final report must use separate tables or clearly separated columns for:

### Production-representative results

- no CPU isolation,
- CFS scheduling,
- performance governor,
- real-data frames,
- observed system-level response-time behavior.

### Controlled engine results

- dedicated isolated CPU,
- performance governor,
- frozen synthetic or captured inputs,
- implementation-level timing behavior.

### Bridge results

- identical inputs under both profiles,
- measured interference inflation,
- explanation of how isolated and production results relate.

Never merge samples from the two profiles into one percentile or maximum.

---

## Claims That Are Allowed

Examples:

- "Under controlled isolated-core conditions, the Rust implementation had a lower observed maximum than the C++ implementation on every frozen fixture."
- "Under the production-like CFS configuration, the real-data replay observed N deadline overruns."
- "The production-like environment increased the maximum latency of the legal-worst fixture by X% relative to the isolated-core profile."
- "The deterministic work counters were identical for the samples included in the cross-language timing comparison."

## Claims That Are Not Allowed

Do not write:

- "The measured maximum is the WCET."
- "Core-isolated timing directly predicts Autoware end-to-end latency."
- "The production trace proves the absence of worse scheduler interference."
- "Equal iteration counts prove equal algorithmic work."
- "A performance-governor setting removes all timing variability."
- "A small-sample EVT fit is a certified pWCET."

---

## Completion Criteria for the Coding Agent

The measurement task is complete only when all of the following are true:

- both measurement profiles are implemented,
- the governor is verified programmatically,
- controlled runs verify affinity and isolation,
- raw per-sample timing data is preserved,
- deterministic work certificates are preserved,
- unequal-work samples are excluded from direct ratios,
- the bridge experiment is complete,
- warm-cache and cold-cache series are separate,
- experiment manifests are saved,
- all reported tables are generated from raw data,
- claims are labeled as controlled, production-representative, or bridge results,
- no measured value is presented as a certified hard WCET.


