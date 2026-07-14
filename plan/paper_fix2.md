# Paper revision round 2 — addressing `paper/review2.md` — Roadmap

## Goal

Resolve the second review's verdict (**Weak Reject / Major Revision**, overall 6.5/10, projected
~8/10 after fixes) in `paper/review2.md`. The reviewer confirms that round 1 was substantive
(K = 8 vs 27, N_pass, measurement protocol, EVT gating, real-data denominator, Pareto search,
AArch64 all resolved) and identifies one remaining load-bearing beam:

> equal iteration count → equal work → Rust counter worst case transfers to C++

is not proven by the current certificate. The reviewer's six priority items:

1. add a **per-input C++/Rust trace certificate** (instrumented C++ analysis build) (review #1, #2),
2. retract or redefine **"bit-exact over D"** (review #1),
3. add a **per-point term to the work model** and use implementation-specific kd counters (review #3, #2),
4. fix the **bridge experiment** sample accounting and causal wording (review #6),
5. split real-data timing into **473 certified / 501 all** frames (review #8),
6. state the **10 Hz infeasibility on the Pi 4** explicitly (review #9),

plus wording-level items (#4, #5, #7), statistics scoping (EVT CI, regression "predictive"),
and the editorial/reproducibility list.

This roadmap only plans the work; it does not edit the paper. Review points are cited as
`#1`–`#9` (the numbering under 「主要な問題点」 in `paper/review2.md`), `#stats`
(統計・回帰についての追加コメント), and `#edit` (編集・再現性上の修正).

## Review-validity audit (what we verified, 2026-07-13)

Every point was checked against `paper/sections/*.tex`, `paper/tables/*.tex`,
`paper/data/*.json`, and the experiment infrastructure. Verdicts:

| # | Review claim | Verdict | Evidence |
|---|---|---|---|
| 1 | "bit-exact over D" is contradicted by the paper's own data; equal iteration is neither sufficient for equal work nor for D membership | **Valid** | All 28 divergent frames lie inside D (max K = 9 ≤ 64, `data/realdata.json`), yet their iteration counts differ — a direct counterexample to `03-methodology.tex` §C "The equivalence holds on the bounded-neighbor domain D". No C++-side Σnbr/Σkd instrumentation exists anywhere in the tree (verified: the only C++-side counting is the `bench/alloc_count.c` LD_PRELOAD interposer + the engine's own `iteration_num`); an instrumented analysis build is mentioned only as a hypothetical (`03-methodology.tex`, `plan/ndt_timing_measurement_policy.md:330`). |
| 2 | C++ Σkd is not measured; interpreting the regression kd coefficient as ns/kd-node is unjustified | **Valid** | `kd_nodes_visited` is a counter of the *Rust* flat-array kd walk; the C++ engine traverses its own pcl/FLANN structures, never counted. `tables/regression.tex` fits both engines on the shared (Rust) counters. |
| 3 | Work model lacks the per-point fixed-cost term; T_solve occurs N_iter, not N_pass, times | **Valid** | The regression is `T ≈ a·Σnbr + b·Σkd + c` (no N_pts term) while the paper itself attributes the subnormal/cache-hostile outliers to per-point constant overhead, with worst LOOCV misses of 75%/92%. Eq (1) (`02-problem.tex`) places T_solve inside the N_pass bracket; the initial pass has no Newton solve. |
| 4 | "Every term enforced by construction" conflicts with the preconditions table; "engine-API worst case" naming is unsafe | **Valid (wording)** | `03-methodology.tex` Layer 1 says every term of Eq (1) is enforced in the Rust engine, but P ≤ 1500 is a preprocessing assumption and N_leaves is memory-parametric (`tables/preconditions.tex`). The C++ API accepts inputs outside D. |
| 5 | Search ablation's initial conditions are unfair (optimal seed vs random init); champion difference under-reported; "worst input" naming | **Valid** | `data/search_ablation.json`: every hill run saturates at `saturation_eval: 1` — the domain-informed seed already attains the maximum (the paper concedes this). The two time-fitness champions' 12,009,768 vs 12,009,329 are `kd_nodes_visited` values (Δ = 439 ≈ 0.004%) — reviewer calls them fitness values, harmless. Per-evaluation search logs were **not persisted** (only stdout; `assemble_ablation.py` notes the scratch summaries are gone), so time-rank reporting needs re-runs. |
| 6 | Bridge: sample imbalance (A = 100 vs B = 3000), "wider margins" is backwards, isolation-flag causality overstated | **Valid, data-confirmed** | `data/bridge.json`: synthetic A-legs n = 100 vs B-legs n = 3000 (real-frame legs 100 vs 100). legal-worst Rust/C++ max ratio: B 120.784/243.436 = **0.496** → A 121.658/201.789 = **0.603** — the gap *narrows* under Profile A on every input (search-00 0.616→0.648, legal-osc 0.334→0.415), so `05-evaluation.tex` §I "survives under Profile A with wider margins" is wrong in direction (the conclusions do survive: Rust max < C++ max everywhere). The same-boot isolation control compares *different physical cores*, so "the isolation flags themselves tax C++" is stronger than the design supports. |
| 7 | "Profile-A re-capture pending" is stale; "300+3000 pooled" sample accounting is opaque | **Valid** | `06-threats.tex:18` still says pending while `05-evaluation.tex` §G presents Profile-A timing and `data/realdata.json` meta records the Profile-A run (2026-07-13, `realdata-profileA/openloop`). `\envIters` = "300+3000 pooled across sessions" (= 3 sessions × (100 warm + 1000 tail)) is never decoded in the paper. |
| 8 | Real-data timing must be split: 501 all-on-map vs 473 certified frames; contracts claim too strong; abstract phrasing | **Valid; split feasible from existing data** | `data/realdata.json` frames carry `match`, `cpp_ms`, `rust_ms`, `counters` → both subsets' percentiles are recomputable offline. Caveat: only a single shared `iteration_num` is stored (no separate C++/Rust counts), so the per-divergent-frame iteration-delta table needs a re-capture (C2). The legality verifier was never run on the capture; only P ≤ 1500 and K ≤ 9 were observed. |
| 9 | Pi 4 results should state 10 Hz infeasibility, not just headroom; ISA-independence "by construction" overstated | **Valid** | Profile-C data: search-00 ≈ 9.85 s (98× budget), legal-worst ≈ 1.50 s (15×), legal-osc ≈ 0.84 s (8×) — the serial configuration is not schedulable at 10 Hz on the Cortex-A72 even at the deployment-tier witness. FMA/lowering/denormal caveats on "by construction" are fair; the 8-fixture counter transfer is the actual evidence. |
| stats | EVT bootstrap CIs on dependent data are not rigorous CIs; "predictive" regression hides 75–92% worst misses | **Valid (minor)** | `tables/evt.tex` already frames the q_10⁻⁹ column as the *reason extrapolation is withheld*; needs one explicit "not a valid CI under dependence" sentence. Regression scoping is a one-sentence fix (B2 adds the missing term anyway). |
| edit | TODOs, exact commits, artifact DOI, subnormal A/B era, WCET(P) naming, allocator wording, "machine-checked" | **Valid** | Commits/hashes exist in the JSON manifests (`cpp_commit`/`rust_commit`/fixture hashes) but are not yet surfaced in the paper; the subnormal shell A/B is still pre-protocol (`\oneoffShell*`); author TODO remains (user-side). |

Where the review slightly overstates (usable in the rebuttal letter):

- The 12,009,768/12,009,329 pair are kd-counter values of the two time-fitness champions, not
  wall-clock fitness readings; the substantive point (nearly identical champions, ranked
  differently) stands.
- The equal-work certificate is not *only* `iteration_num`: on frozen fixtures it also asserts
  final-pose agreement and both convergence scores, and the allocation-count leg independently
  re-derives P·N_pass on the untouched C++ binary. This narrows, but does not close, the gap the
  reviewer identifies — Σnbr/Σkd equality is still unverified on the C++ side, which is exactly
  what C1 adds.
- "preprocessing contracts hold empirically" — the paper's claim is based on observed P and K
  only; the reviewer's requested weakening is correct, but the legality *verifier* does exist
  (`wcet_search_legal.rs`) and can be run over the capture as a cheap strengthening (B1 option).

## Phase A — prose/logic fixes (no new experiments)

Ordering inside A: **A5/A6 first** (a referee can check the bridge numbers and the stale
sentence against our own tables), then A1 (core reframing), then the rest.

### A1 (#1) Retire "bit-exact over D"; re-scope the transfer to certified inputs — **DONE (2026-07-13, commit 58251c7)**

- Rationale: D (bounded-neighbor, truncation-free) is a *necessary* condition for equal work,
  not a sufficient one — the 28 in-D divergent frames prove it. The transfer argument must not
  quantify over D.
- Terminology: replace "bit-exact" throughout (title is already safe) with
  "high-fidelity port, **work-equivalent on individually certified inputs**" (reviewer's
  suggested phrasing). Keep "bit-exact" only where literally true and scoped (e.g. "scores
  bit-identical on 7 of 8 fixtures").
- Formalize two domains in §III-C: D_K = {x : every radius query returns ≤ 64 in-range leaves}
  (geometrically guaranteed for preprocessing-reachable inputs) and the certified subset
  E ⊆ D_K = {x ∈ D_K : the per-input certificate passed}. Every cross-language worst-case claim
  is a claim **over E**, exhibited input by input; D_K is the domain where certification is
  *expected* to succeed (and did, on 8/8 fixtures and 473/501 on-map frames).
- State explicitly that equal `iteration_num` is a necessary-condition check, upgraded on the
  frozen fixtures by pose/score agreement and the allocation-count leg, and upgraded to a full
  trace certificate by C1. Until C1 lands, mark Σnbr/Σkd equality on C++ as *inferred, not
  measured*.
- Files: `main.tex` abstract, `sections/01-introduction.tex` (para 3, contribution 2),
  `sections/03-methodology.tex` §C, `sections/04-implementation.tex` (cap paragraph),
  `sections/06-threats.tex` §C, `sections/07-related.tex`, `sections/08-conclusion.tex`.
- Acceptance: no unscoped "bit-exact" remains (`grep -in 'bit-exact' sections/ main.tex` — every
  hit either scoped-and-literal or replaced); the transfer claim quantifies over E, never D_K.

### A2 (#2) Re-label the kd counter as a Rust-reference proxy — **DONE (2026-07-13, commit 58251c7)**

- Until C1 provides a C++-native counter: rename Σkd in the regression context to
  "Rust-reference kd-node count (a geometry-correlated traversal proxy)"; retract the
  "ns per kd node" reading for the C++ coefficient in §V-F and the Table `regression` header;
  add one sentence that the two engines' traversal structures differ (pcl/FLANN vs flat array)
  so per-node cost is defined only for Rust.
- Note the Pareto-frontier finding (Rust-only re-ranking) as *consistent with* this caveat —
  the reviewer makes this connection; adopt it.
- Files: `sections/05-evaluation.tex` §B/§F, `sections/02-problem.tex` (counter definitions),
  `paper/scripts/gen_tables.py` (regression table header), `sections/03-methodology.tex` §D.
- Acceptance: no sentence interprets the C++ kd coefficient as a physical per-node cost.

### A3 (#4) Scope "enforced by construction"; rename the engine tier — **DONE (2026-07-13, commit 58251c7)**

- Layer 1 sentence → "For fixed external parameters P and N_leaves, the internal multiplicative
  terms (N_iter, K) are enforced by construction; P and N_leaves are caller-side contracts
  (Table preconditions)."
- "engine-API worst case" → "**bounded-neighbor engine tier** (engine tier over D_K)" in
  abstract, intro contribution 4, §V-G heading text; keep one sentence explaining that the raw
  C++ API additionally accepts inputs outside D_K, already reported as the uncapped structural
  hazard.
- Files: `sections/03-methodology.tex` §A, `main.tex` abstract, `sections/01-introduction.tex`,
  `sections/05-evaluation.tex` §G, `sections/06-threats.tex` §D.
- Acceptance: Layer 1 and Table preconditions no longer contradict; tier naming consistent.

### A4 (#5) Re-scope the ablation conclusions; "counter-extremal" naming — **DONE (2026-07-13, commit 58251c7)**

- Rewrite §V-B ablation paragraph to claim exactly what the design supports: (i) the analytic
  construction attains the Σnbr maximum (the seed, not the climb); (ii) the climb's
  contribution is +35% Σkd; (iii) counter fitness is reproducible where wall-clock fitness was
  not (same seed, different champions, kd 12,009,768 vs 12,009,329 — Δ0.004%, i.e. two
  near-identical maxima ranked differently by noise). Drop any implication that hill-climb was
  shown to beat random *search* from equal initial conditions; note the random arm starts from
  random genomes (design limitation, C6 optionally closes it).
- Rename "worst input" → "counter-extremal input" (or "high-work frontier input") wherever the
  input is the search champion rather than a measured time-maximum; keep "time-worst" only for
  measured statements (search-00 remains the C++ time-worst; on Rust the kd-heavy frontier
  member exceeds it — already reported).
- Files: `sections/05-evaluation.tex` §B, `sections/03-methodology.tex` §B,
  `sections/01-introduction.tex` contribution 3, `main.tex` abstract.
- Acceptance: the three supported claims are the only ablation claims; champion Δ quantified.

### A5 (#6) Bridge: fix the direction error, weaken causality, disclose sample imbalance — **DONE (2026-07-13, commit 58251c7)**

- **Direction fix (referee-checkable):** "every cross-engine conclusion … survives under
  Profile A with wider margins" → "… survives under Profile A, although the relative gap
  narrows (e.g. legal-worst max ratio 0.50 → 0.60)". Verified from `data/bridge.json`.
- Causality: "the isolation flags themselves tax the C++ engine by 37–42 ms" → "Profile B is
  associated with a 37–42 ms higher C++ per-align constant; the same-boot control varies the
  core and the isolation flags together, so the responsible mechanism is unresolved" — list the
  physical-core confound; keep the ruled-out factors list as evidence, not proof. (C4 is the
  clean two-boot experiment if we want the causal claim back.)
- Sample accounting: state in §V-H and the Table `bridge` caption that synthetic A-legs are
  n = 100 vs pooled B-legs n = 3000 (real-frame legs 100 vs 100), and that max-vs-max across
  unequal n biases the B max upward; add median ratios (robust to n) alongside. C3 equalizes.
- Files: `sections/05-evaluation.tex` §H, `sections/06-threats.tex` §E (bridge warning),
  `paper/scripts/assemble_bridge.py` + `gen_tables.py` (caption/macros).
- Acceptance: no direction-inverted sentence; no unqualified causal claim; n disclosed.

### A6 (#7) Kill the stale sentence; decode the sample accounting — **DONE (2026-07-13, commit 58251c7)**

- Delete/replace `06-threats.tex:18` "(Profile-A re-capture pending)" — the Profile-A replay
  exists (`data/realdata.json` meta, 2026-07-13). Replace with the actual remaining limit:
  single-shot timing per frame (n = 1 per frame per engine) in the Profile-A replay.
- Decode "300+3000" everywhere it appears (`\envIters`, Table `tails` caption): "3 sessions ×
  (100 warm + 1000 tail) samples per fixture per engine, pooled" — one canonical phrasing,
  emitted from `gen_tables.py`.
- Files: `sections/06-threats.tex` §A, `paper/scripts/gen_tables.py` (env/tails macros),
  `sections/05-evaluation.tex` §A.
- Acceptance: `grep -n 'pending' sections/` clean; a reader can derive 3300 samples/fixture.

### A7 (#9) Pi 4: state the feasibility result; fix the ISA wording — **DONE (2026-07-13, commit 58251c7)**

- **Scope note (2026-07-13, from the author):** the production system will use a CPU
  substantially faster than the Pi 4; the Pi 4 is the *evaluation platform* for the
  \texttt{no\_std} kernel deployment class, not the production ECU. The feasibility statement
  must therefore not read as a product-infeasibility claim.
- Add to §V-J and the conclusion, scoped accordingly: "On the evaluated Cortex-A72 target the
  serial configuration is **not schedulable at 10 Hz** — the deployment-tier witness costs
  ~15× the budget — which we read as a quantification of the per-unit-work speedup the
  production platform must provide over this reference silicon (≈15× on the deployment
  witness; for calibration, the measured x86 desktop host is 12–16× the A72 per unit work and
  still misses the same witness by 1.2×). The affine $T(P)$ law lets any candidate platform be
  audited with a single on-target P-sweep." Levers if the platform alone does not close the
  gap: P reduction, parallelization (4 A72-class cores), SIMD, algorithmic change.
- Audit the paper's framing of the Pi 4 itself: §III-E currently calls it "the deployment
  hardware" — change to "deployment-class evaluation target" (or equivalent) in §III-E, §V-J,
  and anywhere "deployment hardware/target" implies the production ECU is a Pi 4.
- Extend future work accordingly (on-target P-sweep for the production ECU; multi-core
  interference analog already listed).
- ISA wording: "ISA-independent by construction" → "designed for ISA-stable execution
  (pure-software libm, no FMA contraction in the kernel image) and **verified on all frozen
  fixtures**"; keep the per-fixture certification framing. (C7 optionally adds pose/score/hash
  checks on-target.)
- Files: `sections/05-evaluation.tex` §J, `sections/03-methodology.tex` §E,
  `sections/06-threats.tex` §C, `sections/08-conclusion.tex`.
- Acceptance: the infeasibility sentence exists verbatim-equivalent; no "by construction" claim
  about ISA independence without the verified qualifier.

### A8 (#stats, #edit) Statistics scoping + editorial sweep — **DONE (2026-07-13, commit 58251c7)**

- EVT: add to §V-K and the Table `evt` caption that bootstrap CIs computed on serially
  dependent data are themselves not valid CIs — the q_10⁻⁹ column is retained only as
  diagnostic evidence for withholding extrapolation (or drop the column; keep-and-label
  preferred, since it documents *why*).
- Regression: "the model is predictive" → "predictive on the dense-neighbor and P-sweep regime
  (median LOOCV 6–7%) but inadequate for neighbor-sparse inputs dominated by per-point overhead
  (worst miss 75–92%)" — B2's added term should shrink this; re-check after B2.
- WCET(P) → rename the fitted law to an observed envelope, e.g. T_obs,max(P), in §V-E and
  Table/Fig captions (it is not a hard bound).
- Allocator wording: "forfeits the premise of a finite WCET" → "cannot be given a defensible
  finite bound under this allocator/system model".
- "machine-checked" → "automatically checked by property tests" (all occurrences; avoid
  formal-verification connotation).
- Abstract: "57-minute real urban drive" → "57-minute capture containing 501 on-map matching
  frames" (or equivalent with \realOnMap).
- Contracts claim: "the preprocessing contracts hold empirically" → "the observed P and K were
  consistent with the preprocessing contracts" (unless B1's verifier run upgrades it).
- Reproducibility: surface exact commits (already in JSON manifests: `cpp_commit`,
  `rust_commit`, fixture SHA-256) in §V-A or an artifact paragraph; add artifact
  repository/DOI placeholder; author-email TODO is user-side.
- Page budget: move the Pi-4 stale-baseline detour and the subnormal decomposition detail to an
  appendix/artifact note if space is needed for the C1 certificate material (reviewer's
  suggestion; decide at layout time).
- Acceptance: each bullet greps clean; paper builds; no regression in round-1 fixes.

## Phase B — new analysis from existing data (no re-measurement)

### B1 (#8) Split the real-data table: 501 all / 473 certified / 28 divergent — **DONE (2026-07-13, commit 80ebde9)**

- Extend `paper/scripts/gen_tables.py` to emit from `data/realdata.json`:
  (i) the existing on-map envelope rows recomputed over **all 501 on-map frames** (system-level
  behavior — label as such); (ii) the same percentiles over the **473 certified frames**
  (equal-work implementation comparison — label as such); (iii) a compact divergent-28 summary:
  C++ p50/max, Rust p50/max, Σnbr and K̄ range, share at the iteration cap — everything the
  per-frame records support today. Per-frame iteration deltas and pose/score deltas need C2;
  the table gets a footnote until then.
- Optional cheap strengthening: run the existing legality verifier (`wcet_search_legal.rs`
  invariants) over the captured frames' P/duplicate/crop properties to upgrade the A8 contracts
  sentence from "consistent with" to "checked"; report which invariants were checkable offline.
- Files: `paper/scripts/gen_tables.py`, `tables/realdata*.tex` (generated),
  `sections/05-evaluation.tex` §G prose.
- Acceptance: Table VIII (realdata) no longer mixes divergent frames into an "equal-work"
  comparison; both denominators labeled; gen_tables hard-fails if the subsets drift.

### B2 (#3) Counter-form work model with the per-point term; fix T_solve — **DONE (2026-07-13, commit 80ebde9)**

- Rewrite the bound presentation (add to §II or §V-F) in counter form:
  `T ≤ c0 + c_pt·N_pts + c_nbr·Σnbr + c_kd·Σkd + c_solve·N_iter`, with `N_pts = P·N_pass` —
  this is the model the paper's own subnormal/cache-hostile analysis implies. Amend Eq (1) so
  T_solve multiplies N_iter (initial pass has no Newton solve); note the old form was a safe
  over-bound.
- Re-fit the regression with the N_pts regressor added (data exists: `points_processed` in
  `data/wcet_rust.json` / `data/psweep_rust.json`); report LOOCV again (expect the subnormal/
  cache-hostile misses to collapse), plus collinearity diagnostics for the enlarged design (3
  regressors on n = \regN — expect wider per-coefficient CIs; the prediction, not the
  coefficients, remains the claim).
- Files: `sections/02-problem.tex` (Eq 1 + counters), `paper/scripts/gen_tables.py`
  (regression), `sections/05-evaluation.tex` §F, `sections/06-threats.tex` (precondition rows
  unchanged).
- Acceptance: regression table includes the per-point term; §V-F worst-miss story updated from
  regenerated numbers; Eq (1) solve count correct.

## Phase C — new experiments (priority order)

### C1 (#1, #2 — top priority) Instrumented C++ analysis build + per-input trace certificate — **DONE (2026-07-13, autoware_core ce4ac83a+96e35b85, paper 414605b)**

- Rationale: this is the review's single blocking item. The byte-identical constraint governs
  the shipped sources; a local analysis build is explicitly legitimate (the paper already says
  so; the reviewer insists we act on it).
- How: create an analysis-only copy of the C++ engine (sources under
  `src/core/autoware_core/localization/autoware_ndt_scan_matcher/src/ndt_omp/` +
  headers under `include/autoware/ndt_scan_matcher/ndt_omp/`), guarded behind a dedicated
  CMake target (e.g. `ndt_bench_replay_traced`) that is never part of the shipped source set
  (respects the `NDT_USE_RUST`-style discipline; upstream files stay byte-identical).
  Instrument, mirroring the Rust counters in
  `realtime_ndt_scan_matcher` (feature `wcet_counters`):
  - derivative-pass count, per-pass point count,
  - per-query neighbor count and Σnbr,
  - neighbor leaf IDs + order (FNV/xx hash per pass),
  - line-search evaluation count (expected 0 extra passes; certifies the N_pass claim on C++),
  - **C++-native kd/FLANN node-visit counter** (Σkd^C++, its own definition),
  - score/gradient/Hessian hash per pass, or max ULP delta vs Rust (choose ULP-delta: more
    informative for the knife-edge story).
- Run over: all frozen fixtures (`bench/fixtures/*.ndtfix`, incl. pareto/), and the 501 on-map
  real frames (capture-directory replay mode of `bench/ndt_bench_replay.cpp`).
- Deliverables:
  - a trace-certificate table: per fixture, pass/point/Σnbr/neighbor-hash equality (expected
    exact), score/gradient ULP envelope;
  - E_trace membership counts on real data (expect 473 pass; the 28 divergent frames get their
    first-divergence pass index — turns the knife-edge narrative into measured data);
  - Σkd^C++ per fixture → re-fit the C++ regression on its own counter (replaces the A2 proxy
    caveat with a measurement; keep the Rust fit on Rust counters);
  - paper text: §III-C rewrite around the executed (not hypothetical) analysis build; new
    generated table + macros.
- Infra notes: replay harness `bench/ndt_bench_replay.cpp` already drives both engines on
  identical buffers and prints a cert block — extend its JSON output; `bench/run_wcet.sh` /
  `wcet_campaign.py` drive it; `paper/scripts/integrate_campaign.py` pools into `paper/data/`.
- Acceptance: the review's implication chain is replaced by a measured per-input certificate;
  every cross-language table cites which certificate level (C0 iteration/pose/score, C1 full
  trace) each input passed.

### C2 (#8) Re-capture the real-data replay with per-engine iteration counts — **DONE (rode along with C1: trace_real.json carries per-engine iterations, pose deltas, and per-frame trace verdicts; realdata.json schema unchanged)**

- Extend `bench/wcet_realdata.py` + the replay to persist, per frame: both engines'
  `iteration_num`, pose delta, both scores (and, with C1, the trace-cert verdict + first
  divergent pass). Re-emit `data/realdata.json` (schema v2; keep v1 fields so B1 tables
  regenerate unchanged).
- Deliverable: the divergent-28 table gains iteration-delta (expect ±1), pose/score deltas —
  the reviewer's requested columns.
- Acceptance: B1's footnote removed; divergent table fully populated from regenerated data.

### C3 (#6) Equalize the bridge sample structure

- Re-run the Profile-A leg for the three synthetic inputs at 3 × 1000 samples (mirroring the
  B-leg pooled structure; ~2–3 h of machine time at search-00 rates), or alternatively
  subsample the B-leg to matched n — do the re-run (stronger). Update
  `paper/scripts/assemble_bridge.py`; recompute inflation ratios and the §V-H prose (A5's
  narrowing statement re-verified on matched n).
- Acceptance: max-ratio comparisons are same-n; caption states the matched design.

### C4 (#6, optional — requires host reboots) Isolation-flag causality

- The clean design the reviewer specifies: same physical core, two boots (isolcpus/nohz_full/
  rcu_nocbs present vs absent), same SMT/IRQ/frequency/binary/allocator, interleaved
  measurement, matched n. Requires editing host kernel cmdline + 2 reboots — **user decision**;
  if skipped, A5's "association, mechanism unresolved" wording is final and honest.
- Acceptance (if run): either the causal sentence returns with a defensible design, or the
  effect is re-attributed.

### C5 (#edit) Re-measure the subnormal shell A/B under Profile B

- The null A/B (subnormal vs shifted shell) currently carries pre-protocol timing
  (`\oneoffShell*` macros, flagged "era-specific" in §V-C). Re-run both fixtures under the
  current Profile-B protocol (100 + 1000 samples each); update `ONEOFF` provenance in
  `gen_tables.py`.
- Acceptance: no "pre-protocol environment" caveat remains in §V-C.

### C6 (#5, optional) Ablation arms with fair initial conditions

- Add runs via `realtime_ndt_scan_matcher/examples/wcet_search.rs` env knobs: hand-built seed +
  random mutations (no hill acceptance), random init + hill-climb, alongside the existing arms;
  re-run the time-fitness pair **persisting per-evaluation logs** this time
  (`WCET_SEARCH_JSON`; keep them in `bench/campaign_runs/`), then time both time-champions
  under Profile B to report their time rank. Update `assemble_ablation.py` +
  `data/search_ablation.json`.
- Acceptance: the ablation table separates seed quality from search strategy; champion time
  ranks reported.

### C7 (#9, optional) On-target pose/score/trace comparison

- Extend the Pi-4 kernel app to also emit final pose/score (and, post-C1, the trace hash) per
  fixture and assert against host values, upgrading the cross-ISA certificate beyond counters.
- Acceptance: on-target table gains a pose/score column; A7's "verified" claim covers values,
  not only counters.

### C8 (#9 — recommended, proposed by the author 2026-07-13) Parallel feasibility on x86: legal-worst at 2 and 4 threads — **DONE (2026-07-14, autoware_core d41c7272, paper 323b382)**

- Rationale: on the x86 host the deployment-tier witness misses 10 Hz by 1.2× (legal-worst
  Rust 120.8 ms serial). A7 lists parallelization as a lever; this experiment turns the lever
  from speculation into a measured result — "the contracts buy 4.9×, and the remaining 1.2×
  closes at 2 threads (measured s(k))" is a much stronger ending for the two-tier story.
- Feasibility (verified in-tree): the Rust crate already ships a `parallel` feature
  (rayon-backed `compute_derivatives`, `realtime_ndt_scan_matcher/src/ndt.rs`) whose
  order-preserving `collect_into_vec` reduction is **bit-identical to serial by design**
  ("a pure performance option, never a numeric change"; `align` selects it when
  `params.num_threads > 1`, pool size via `init_thread_pool`/`RAYON_NUM_THREADS`). The C++
  engine natively supports `num_threads` (OpenMP) — the production configuration is
  multi-threaded anyway, so this also adds production relevance.
- Design: threads k ∈ {1, 2, 4}, both engines, on \emph{legal-worst} and \emph{legal-osc}
  (deployment tier — the 10 Hz question) plus \emph{search-00} (engine-tier context). Profile-B
  protocol extended to a multi-core variant: k isolated physical cores, SMT siblings off,
  same warm-series/calibration-guard discipline. Requires enlarging the `isolcpus` set →
  kernel-cmdline change + reboot; **schedule in the same reboot campaign as C4**.
- Certificates: Rust — assert counters, pose, and score bit-identical between serial and
  parallel runs per input (the crate's design claim, now measured); C++ — check whether the
  OpenMP reduction order shifts iteration counts/scores vs serial and report it (expected
  possible; if it diverges, the C++ parallel numbers are a system observation, not an
  equal-work comparison — label accordingly).
- Scoping for the paper: this is a **throughput/feasibility measurement**, not an extension of
  the WCET argument to multi-core — the serial engine remains the deterministic baseline (the
  crate's own stance), and multi-core WCET needs the interference analysis already listed as
  future work. Present as: speedup table s(k) + "legal-worst fits the 100 ms budget at k = …
  on this host"; note load-imbalance sensitivity (skewed per-point K) as the expected
  sub-linearity mechanism.
- Pi-4 note: **not** portable to the bare-metal target as-is — `parallel` implies `std`
  (rayon), and the `mt` no_std build provides engine sharing, not a data-parallel align; an
  on-target parallel align is future work, so C8 is x86-only.
- Files: `bench/wcet_campaign.py` (thread-count axis), `bench/ndt_bench_replay.cpp`
  (`num_threads` plumbing + serial-vs-parallel cert), `paper/scripts/integrate_campaign.py`,
  new generated table/macros; paper §V-G/§V-J prose + A7 lever sentence.
- Acceptance: a measured s(k) table for both engines; the serial-vs-parallel Rust certificate
  passes bit-exactly; the two-tier section states at which k the deployment witness fits
  10 Hz on this host.

## Milestones / ordering

| Milestone | Items | Gate |
|---|---|---|
| M1 — referee-checkable errors | ~~A5, A6~~ (done, 58251c7) | **COMPLETE.** Nothing in the paper contradicts our own published tables/data. |
| M2 — claims re-scoped | ~~A1, A2, A3, A4, A7, A8~~ (done, 58251c7) | **COMPLETE.** The paper no longer claims what the current certificate cannot support; rebuttal letter draftable. |
| M3 — existing-data strengthening | ~~B1, B2~~ (done, 80ebde9) | **COMPLETE.** Real-data table split; work model has the per-point term. |
| M4 — trace certificate | ~~C1, C2~~ (done, 2026-07-13) | **COMPLETE.** Transfer claim backed by a measured per-input C++/Rust trace certificate incl. Σkd^C++; C2's per-engine iteration/pose data rode along in trace_real.json. |
| M5 — measurement cleanups | ~~C8~~ (done, 323b382); C3, C5 pending (+ optional C4, C6, C7) | Parallel feasibility measured; bridge same-n and subnormal re-measure still open. |
| M6 — resubmission package | re-run this audit table against the final PDF; rebuttal letter (include the three push-back notes above) | Submit. |

A before B; C1 can start in parallel with Phase A (different files). B2 lands before C1's
regression re-fit only in prose (the N_pts term is orthogonal to Σkd^C++; final table includes
both). A1's wording deliberately anticipates C1 ("inferred, not measured" → deleted once C1
lands).

## Acceptance checklist (review point → roadmap item)

- #1 → A1 + C1 - #2 → A2 + C1 (Σkd^C++) - #3 → B2
- #4 → A3 - #5 → A4 (+ C6 optional) - #6 → A5 + C3 (+ C4 optional)
- #7 → A6 - #8 → B1 + C2 + A8 (abstract/contracts wording) - #9 → A7 + C8 (+ C7 optional)
- #stats → A8 (EVT CI, regression scoping) + B2 - #edit → A8 + C5 (+ user: author block)
- Reviewer's page-budget advice → A8 (appendix decision at layout time).

## Status log

- 2026-07-13: roadmap written; review2 validity audit completed (all major points valid; three
  rebuttal-grade nuances recorded above). No paper edits yet.
- 2026-07-13 (later): A7 re-scoped — the Pi 4 is the evaluation platform, not the production
  ECU (author input): feasibility statement reframed as a per-unit-work speedup requirement.
  C8 added (author proposal): x86 parallel feasibility of the deployment tier at 2/4 threads;
  in-tree support verified (Rust `parallel` feature is bit-identical-by-design, C++ has
  OpenMP `num_threads`).
- 2026-07-13 (later still): **M1+M2 done** (commit 58251c7) — A5/A6 and A1--A4/A7/A8
  executed as one batch (same files). New generated macros: bridge gap pair (0.50/0.60,
  guarded both directions), \ablationTimeKdDeltaPct (0.004%), per-session sample decode
  (100 warm + 1000 tail), \raspiLegalWorstBudgetX (15), \raspiHostFactorMin/Max (12--18),
  \legalWorstBudgetXRust (1.2). "bit-exact" survives only as literal, measured
  "bit-identical" statements + the RustBelt citation's "machine-checked". Page count
  13 -> 14 (references spill); appendix decision deferred to the C1 layout pass.
- 2026-07-13 (later still): **M3 done** (commit 80ebde9). B2's headline finding: the
  missing per-point axis is real and engine-asymmetric -- C++ c_pt = 2.45 [1.2, 3.2]
  us/pt (matches the Sec. V-C overhead; worst LOO 75% -> 16%), while for Rust the term is
  degenerate (negative c_pt, worst LOO 92% -> 228%), consistent with the port removing
  that machinery. Adopted models: C++ 4-term, Rust 2-term, both shown with guards. B1:
  realdata table now reports all-on-map (501) and certified (473) align rows plus
  divergent-28 summary macros; per-engine iteration deltas deferred to C2. Note for the
  optional B1 verifier run: not done (contracts sentence stays at "consistent with").
  Page count 14 -> 15.
- 2026-07-13 (night): **M4 done — C1 executed** (autoware_core ce4ac83a + 96e35b85; paper
  414605b). Traced analysis build (bench/traced/, NDT_BUILD_TRACED) + Rust `wcet-trace`
  mirror + per-leg replay comparison. Headline findings: structural legs exact on all 18
  fixtures; on real data 172/473 equal-iteration on-map frames do equal-iteration-but-
  unequal-work (<= 3.61% kernel-work delta) -- equal iteration measured as necessary-but-
  not-sufficient, E_trace = 22,216/22,416; f64 streams differ by design (FLANN distance
  sort vs kd-visit order; score <= 12 ULP on well-conditioned fixtures, ~1e12 on knife-edge);
  regression kd regressor now engine-own (C++ 2-term worst LOO 75% -> 42%; c_pt no longer
  separately identified, CI covers zero -- prose re-scoped). C2 rode along: per-engine
  iterations, pose deltas (divergent frames fork late, +-13 iters, <= 0.40 m), per-frame
  verdicts in trace_real.json. Open-loop guess rewrite now scripted
  (bench/rewrite_guesses.py). Remaining in phase C: C3 (bridge same-n), C5 (subnormal A/B
  re-measure), C8 (parallel feasibility), optional C4/C6/C7.
- 2026-07-14: **C8 done** (autoware_core d41c7272, paper 323b382). Isolated-core parallel
  measurement. Key detour: on isolcpus cores unpinned rayon workers pile onto one core
  (isolcpus disables auto load-balancing), so init_thread_pool gained opt-in per-worker
  pinning (NDT_PIN_RAYON_WORKERS); and C++/Rust must run in separate process invocations
  (libgomp pins the main thread, contaminating a same-process rayon run). Result: both
  engines ~near-linear (Rust 3.9x, C++ 3.3x at k=4); legal-worst 122.9 -> 61.0 ms at k=2
  (fits 10 Hz). Note: an earlier uncommitted WCET_THREADS edit was lost in the reboot and
  had to be re-applied; also colcon now needs `source install/local_setup.zsh` +
  `--base-paths src/core`. Remaining Phase C: C3 (bridge same-n), C5 (subnormal A/B
  re-measure) -- both need the 3.2 GHz reference-clock host, which is now configured.
