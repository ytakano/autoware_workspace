# Paper revision round 3 -- addressing `paper/review3.md` -- Roadmap

## Goal

Revise the manuscript so that every cross-language, work-bound, and timing claim matches
the evidence already present in the frozen artifacts. The central correction is to separate
the base certificate from the trace certificate and state precisely which work is common
across implementations.

This round is limited to manuscript work:

- prose, notation, captions, and section structure;
- paper-local table and macro generation;
- analysis derived from existing frozen JSON files;
- regeneration and validation of the paper.

Production Rust/C++ changes, new measurements, matched-flag ablations, C++-specific search,
neighbor-overflow instrumentation, a boundary validator, and closed-loop experiments are
out of scope. Where the review requests unavailable evidence, narrow the claim and record
the missing evidence as future work. Do not invent results or submission metadata.

## Evidence invariants

All revisions must preserve this partition from `realdata.json` and `trace_real.json`:

| Set | All frames | On-map frames | Meaning |
|---|---:|---:|---|
| Captured population | 22,416 | 501 | Every replayed frame |
| Base-certified, \(E_{\mathrm{base}}\) | 22,388 | 473 | Equal iteration-level/base verdict |
| Trace-certified, \(E_{\mathrm{trace}}\) | 22,216 | 301 | Equal common semantic work under the trace certificate |
| Base-only | 172 | 172 | Equal iteration count but unequal common semantic work |
| Iteration-divergent | 28 | 28 | Base certificate fails |

Required arithmetic:

```text
301 + 172 + 28 = 501
22,216 + 172 + 28 = 22,416
301 / 501 = 60.1%  (rounded to one decimal place)
200 / 501 = 39.9%  (not trace-certified)
```

The 28-frame residual is an iteration-level divergence residual. It is not the full set of
frames lacking a trace certificate.

## Review-validity audit

| Review point | Assessment | Response |
|---|---|---|
| 1. Real-data certificate rates conflict | **Valid, critical** | Split \(E_{\mathrm{base}}\) and \(E_{\mathrm{trace}}\); regenerate the table and dependent prose. |
| 2. "Equal work" overstates the certificate | **Valid, critical** | Define common semantic work separately from engine-specific work. |
| 3. Bound/worst/WCET vocabulary is too strong | **Valid, critical** | Separate analytic work bounds, witnesses, and observed maxima. |
| 4. Base agreement does not prove membership in \(D\) | **Valid** | Remove the runtime-membership claim and disclose the missing direct check. |
| 5. Build conditions and implementation confounds | **Valid in part** | Correct the manifest contradiction and frame results as implementation comparisons. |
| 6. Search ablation mixes seed and strategy | **Valid but already disclosed** | Retain only demonstrated seed and traversal-growth claims. |
| 7. Functional residual needs more weight | **Valid in part** | Report both 172 and 28 prominently; keep unavailable metrics as future work. |
| Table III certificate caption | **Valid** | Attribute fixture certification to the full trace. |
| Table X mixes populations | **Valid** | Separate all-frame checks from on-map timing and certification. |
| Regression is weakly identified | **Valid but disclosed** | Demote coefficient attribution and keep fixture comparisons primary. |
| Parallelism is not a WCET result | **Valid** | Reframe as host throughput/deadline feasibility. |
| \(K \le 27\) assumptions need precision | **Valid** | State geometric assumptions and scope \(K=8\) to the lattice witness. |
| Hash agreement called "exact" | **Valid** | Disclose FNV collision risk and avoid literal set-equality language. |
| Related work and manuscript length | **Editorial** | Tighten after correctness fixes. |
| Author/artifact TODOs | **Valid submission blockers** | Keep blockers until real values are supplied. |

## Phase A -- correctness blockers

### A1 -- Separate base and trace certificates -- **COMPLETED**

Use two named sets consistently:

- \(E_{\mathrm{base}}\): inputs passing the iteration/pose/score base verdict;
- \(E_{\mathrm{trace}}\): inputs whose pass structure, point counts, neighbor counts, and
  per-point neighbor-set hashes agree.

Required changes:

- Replace the unqualified certified subset \(E\) with the appropriate named set.
- Use \(E_{\mathrm{trace}}\) for every strict cross-language common-work statement.
- Describe 473/501 as the base-certificate rate, not an equal-work rate.
- Describe 301/501, or 60.1%, as the on-map trace-certification rate.
- State that 172 frames pass base but fail trace, and 28 fail at the iteration level.
- Update the abstract so 28 frames are not presented as the only discrepancy.
- Update the introduction, methodology, evaluation, threats, related work, and conclusion.
- Add generator macros and hard guards for both partition equations.
- Fail generation on duplicate, missing, or unjoinable `seq` values.

Acceptance:

- No text calls 473/501 the strict or equal-work-certified subset.
- Every strict comparison is scoped to 301 on-map or 22,216 total frames.

### A2 -- Define common semantic work -- **COMPLETED**

Replace unqualified "equal work" with "equal common semantic work" for the certificate.

Define:

```text
W_common =
  (derivative-pass structure,
   points processed per pass,
   point-neighbor evaluation counts,
   per-point neighbor-leaf sets)

W_cpp_specific =
  (FLANN distance/plane evaluations,
   result-container and allocator work,
   implementation-specific memory/control operations)

W_rust_specific =
  (Rust kd-tree nodes examined,
   flat-buffer and implementation-specific memory/control operations)
```

Clarify that the trace compares \(W_{\mathrm{common}}\), not total instructions, traversal,
memory traffic, allocations, or latency. Eq. (1) is instantiated per engine because search
and traversal are implementation-specific. A transferred input is a shared certified
witness, not proof that it stresses both engines equally.

Acceptance:

- Audit every occurrence of `equal work`, `equally`, and `same work`.
- Captions and table notes use the same terminology as Methodology.

### A3 -- Separate upper bounds, witnesses, and observations -- **COMPLETED**

Use this vocabulary:

- **analytic work upper bound** for a formula proved under contracts;
- **parametric traversal bound** when it depends on \(N_{\mathrm{leaves}}\);
- **constructed stress witness** for a frozen fixture;
- **observed maximum** for the largest measured sample;
- **measured witness-to-witness gap** for the 4.9x/4.0x comparison;
- **no certified hard timing bound** for the timing conclusion.

Specific changes:

- Rename "Two-tier bound" to "Two-tier work-envelope analysis".
- Replace "fixtures bound the engine" with searched-family witness language.
- Rename `union-worst` to `shared counter-extremal witness`; retain `search-00` as the ID.
- State that a Rust Pareto candidate exceeds `search-00` by 1.1%, while `search-00`
  remains C++ time-worst among evaluated shared fixtures.
- Replace "does not regress WCET" with an observed-maximum statement.
- Keep 4.9x/4.0x as measured fixture gaps and 64/27 as the contract-derived kernel factor.

Acceptance:

- No fixture is described as an upper bound.
- Every timing result is labeled observed, measured, or platform-specific.

### A4 -- Correct \(D\), overflow, and allocation claims -- **COMPLETED**

Remove the claim that the base certificate is a runtime membership test for \(D\).

State instead:

- \(D\) requires every uncapped query to have at most 64 in-range leaves;
- the normal Rust engine caps at 64 but does not report a 65th-neighbor overflow;
- the analysis trace gives retrospective evidence on evaluated inputs, subject to B3;
- deployment membership and preprocessing contracts remain unvalidated assumptions;
- an overflow flag, boundary validator, and rejection behavior are future work.

Scope zero allocation to buffers pre-reserved for the declared envelope. Exceeding capacity
can trigger growth allocation; this round does not change growth into rejection.

Acceptance:

- Table XIV, Methodology, Implementation, and Threats agree on violation behavior.
- No absent runtime check is presented as enforced.

### A5 -- Correct build and reproducibility statements -- **COMPLETED**

Correct C++ flags to the frozen manifest:

```text
CMAKE_BUILD_TYPE=Release
CMAKE_CXX_FLAGS_RELEASE="-O3 -DNDEBUG"
```

Report the Rust workspace release configuration:

```text
opt-level=3             (Cargo release default)
lto=false               (no explicit override)
codegen-units=16        (Cargo release default)
overflow-checks=true    (workspace override)
target-cpu not explicitly set
no experiment-specific RUSTFLAGS recorded
```

State that results compare two implementations, not languages in isolation. Allocator,
layout, kd-tree, container, and libm differences are part of the measured delta. Matched
flags, bounded C++, and component ablations remain future work.

Submission blockers:

- replace author/email/affiliation TODOs only with author-supplied values;
- add a DOI/URL only after an immutable artifact exists;
- list fixtures, manifests, logs, scripts, and generation commands in the artifact record.

## Phase B -- existing-data presentation and editorial fixes

### B1 -- Rebuild the real-data table around \(E_{\mathrm{trace}}\) -- **COMPLETED**

Join `realdata.json` and `trace_real.json` by `seq` in the paper-local generator. Do not
modify either frozen JSON file.

Rebuild the table as two panels:

1. **All-frame contract observations**, over 22,416 frames: \(P\), max \(K\), and counts for
   \(E_{\mathrm{base}}\), \(E_{\mathrm{trace}}\), base-only, and divergent frames.
2. **On-map timing and comparison**, over 501 frames: all-on-map timing as a system-level
   observation and trace-certified timing over the 301-frame \(E_{\mathrm{trace}}\) subset.

Remove the 473-frame "certified" timing rows or label them as base diagnostics. They must
not be the strict implementation comparison.

Acceptance:

- All-frame max-\(K\) statistics cannot be mistaken for on-map results.
- Strict timing rows contain exactly 301 samples per engine.
- Generation is deterministic and partition-guarded.

### B2 -- Re-scope search, regression, and parallel results -- **COMPLETED**

Search:

- Credit analytic construction with kernel-count saturation.
- Credit hill-climb only with the measured traversal increase.
- Do not claim random-arm superiority because initial genomes differ.
- State that only the archived Pareto frontier was re-timed on C++.

Regression:

- Present the model as a diagnostic decomposition, not reliable unit-cost identification.
- Lead with 0.99 correlation, wide intervals, and 92% Rust worst leave-one-out error.
- Keep direct per-fixture maxima as the resolved comparison.
- Remove coefficient-level causal attribution from headline results.

Parallelism:

- Rename the subsection "Host throughput scaling and deadline feasibility".
- State immediately that it is not a multi-core WCET result.
- Describe sub-100 ms as an observed host result, not certified schedulability.

### B3 -- Tighten geometry, hash, and functional-fidelity wording -- **COMPLETED**

Geometry:

- State assumptions: one leaf per occupied voxel per tile, disjoint deployment tiles,
  search radius equal to voxel size, and centroid containment.
- Treat boundary inclusion and floating-point radius comparison as assumptions.
- Restrict \(K=8\) to the voxel-center/corner-lattice witness.

Trace hash:

- Name the FNV-1a leaf-mean-bit hash.
- Replace "neighbor sets exact" with "neighbor counts and hashes agree".
- Disclose non-zero collision risk and lack of formal set-equality proof.

Functional fidelity:

- Report median, high percentile, and maximum available from `trans_delta_m`.
- Keep maximum iteration and translation deltas visible.
- State that rotation error, absolute/relative score error, quality-gate changes, filter
  innovation, nominal-prior behavior, and closed-loop effects were not captured.
- Clarify that "drop-in replacement" means ABI/API substitutability, not closed-loop
  behavioral equivalence.

### B4 -- Captions, related work, and compression -- **COMPLETED**

- Fix Table III so fixture certification is attributed to the full trace.
- Ensure every table states its population and certificate level.
- Add a compact claim/evidence/scope table only if it replaces more prose than it adds.
- Tighten repeated caveats after terminology is centralized.
- Add one concise related-work paragraph on deterministic cost-guided search.
- Move low-priority regression, EVT, Pi debugging, or parallel detail to an appendix only
  if needed to keep the main paper at or below 17 pages.

## Milestones and ordering

1. **M1 -- Certificate consistency:** A1 and B1.
2. **M2 -- Claim semantics:** A2 and A3.
3. **M3 -- Contract and reproducibility scope:** A4 and A5.
4. **M4 -- Secondary-result cleanup:** B2 and B3.
5. **M5 -- Editorial compression and submission audit:** B4.

Do not start broad compression before M1--M3; otherwise prose may be polished around
definitions that still need to change.

## Validation

Run:

```sh
cd paper
make tables
python3 scripts/evt.py
make main.pdf
```

Then verify:

- no undefined references or citations;
- no new overfull boxes from revised tables/headings;
- `git diff --check` passes;
- production sources and `paper/data/*.json` are unchanged;
- tables regenerate deterministically;
- all certificate counts satisfy the Evidence invariants;
- manually audit searches for `equal work`, `union-worst`, `fixtures bound`, `worst case`,
  `WCET`, and `certified`.

## Acceptance checklist

- [x] \(E_{\mathrm{base}}\) and \(E_{\mathrm{trace}}\) are distinct everywhere.
- [x] On-map trace certification is 301/501, or 60.1%.
- [x] Both 172 base-only and 28 iteration-divergent frames are visible.
- [x] Cross-language claims concern common semantic work only.
- [x] Engine-specific traversal and runtime work remain separate.
- [x] Fixtures are witnesses, not upper bounds.
- [x] Timing maxima are empirical observations, not WCET.
- [x] Membership in \(D\) is not claimed runtime-enforced.
- [x] Zero allocation is conditional on pre-reserved capacities.
- [x] The paper reports actual C++ `-O3 -DNDEBUG`.
- [x] Search, regression, and parallel claims match their designs.
- [x] Hash collision risk and geometric assumptions are disclosed.
- [x] Author and artifact placeholders remain explicit blockers.
- [x] The PDF builds within the submission page budget.

## Status log

- 2026-07-14: Roadmap created from `paper/review3.md`; all tasks pending.
- 2026-07-14: Implemented all manuscript and generator changes; validation passed at
  17 pages with deterministic tables and unchanged frozen data.
