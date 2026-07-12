# Paper revision — addressing `paper/review.md` — Roadmap

## Goal

Make the WCET paper (`paper/main.tex`) defensible for resubmission by resolving the review's
verdict (Major Revision / Reject-and-Resubmit) in `paper/review.md`. The review's own assessment:
the idea is strong (novelty 4.5/5, industrial relevance 4.5/5) and the gaps are execution, not
concept — fixing the blocking items targets its stated 7–8/10 resubmission score.

The reviewer's five blocking items:

1. the **K = 8 vs K ≤ 27** deployment-tier contradiction (review #1),
2. **equal iteration count ≠ equal work** certification (review #3),
3. the **Rust cap-64 vs C++ uncapped** input-domain mismatch (review #2),
4. **pWCET statistics** (n=10 Gumbel, internal contradictions) (review #7),
5. **measurement under target conditions** (review #6),

plus the data-integrity issues (#8 stale prose numbers, #10 effective real-data sample size).

This roadmap only plans the work; it does not edit the paper. Review points are cited as
`#1`–`#11` (the numbering in `paper/review.md`).

## Review-validity audit (what we verified, 2026-07-11)

Every review point was checked against `paper/sections/*.tex`, `paper/tables/*.tex`, and the
frozen data `paper/data/*.json`. Verdicts:

| # | Review claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Deployment-tier K ≤ 8 is refuted by the paper's own max K = 9 | **Valid** | `04-implementation.tex:76` calls K̄ = 8.0 a "deployment geometric ceiling"; `05-evaluation.tex:152-153` itself observes max K = 9 and says "the load-bearing bound is the 27, not the 8". Internal contradiction. Nuance: the 4.6× is a *measured fixture ratio*, not a K=8-derived bound, so the fix is reframing + a K-maximizing legal witness, not a full recompute. |
| 2 | C++ engine-tier worst is not bounded by the Rust search (cap 64 vs uncapped) | **Valid** | `04-implementation.tex` §"Sufficiency of the neighbor cap" concedes C++ cost "grows without bound with tile multiplicity" beyond 64. The abstract's "transfers verbatim" needs a domain qualifier. |
| 3 | Equal iteration count is necessary, not sufficient, for equal work | **Partially valid** | The per-input runtime certificate is only `iteration_num` (`03-methodology.tex` §C); the offline differential suite checks more. Cheaper fixes than the reviewer's instrumented-C++-fork exist (below). Reviewer's "line-search trial counts may differ" is empirically closed on this engine: `derivative_passes == iteration_num + 1` holds on **all 22,416** real frames (checked against `data/realdata.json`). |
| 4 | Work model has an off-by-one and unmodelled passes | **Valid** | Eq (1) (`02-problem.tex:31`) multiplies by N_iter; the saturation identity, property tests, and all experiments use N_iter+1 passes. Needs N_pass as a first-class variable + explicit line-search accounting. |
| 5 | "proven" / "machine-checked" overstates property tests + counting allocator | **Valid (wording)** | `06-threats.tex:63` "the work bound … is proven"; abstract "a proven zero". Fix by tiering evidence strength; the by-construction parts (loop guards, hard cap, fixed arrays) genuinely are structural. |
| 6 | Measurement conditions insufficient for a WCET paper | **Valid** | Conceded by the paper's own red TODOs (`05-evaluation.tex:8-9`, `06-threats.tex:9,12`): powersave governor, container, warm cache, one machine, 100 samples. |
| 7 | pWCET section statistically indefensible + internally contradictory | **Valid, data-confirmed** | `05-evaluation.tex:174` "β ≤ 1.3 ms everywhere" vs `tables/gumbel.tex` β = 15.81/15.41/12.34 ms. "A few percent above the measured maximum" is actually **+28%** (C++ 1201.5/937.4) and **+32%** (Rust 868.9/656.0). Stale prose vs regenerated table. |
| 8 | Result numbers disagree across the paper | **Valid, data-confirmed** | `05-evaluation.tex:30` "876 ms → 608 ms" matches neither Table `tails` (937.4/656.0) nor Table `psweep` P=2000 (891.2/608.6). The adjacent `% DATA-CHECKED` comment verified only the ratio, not the ms values. Root cause: tables are generated (`scripts/gen_tables.py`), prose numbers are hand-typed. |
| 9 | Lexicographic counter search need not find the time-worst input | **Partially valid** | A strengthening request, not an error — the paper already hedges (kd term unsaturated, `06-threats.tex` §B). Pareto-frontier archiving + ablations are worthwhile additions; claims should say "counter-worst". |
| 10 | Effective real-data sample is 501, not 22,416 | **Valid — and worse than the reviewer feared** | Verified from `data/realdata.json`: on-map (sum_neighbors > 0) = 501/22,416; **all 28 divergences are on-map → 5.6% divergence on meaningful frames** (vs the headline 0.12%). Off-map frames are trivial (iteration p50 = 0, C++ p50 ≈ 1.9 ms). This must be disclosed, not discovered by a referee. |
| 11 | Unit-cost regression (n=6, 2 regressors) is under-determined | **Valid** | `tables/regression.tex` n=6, negative Rust intercept (paper flags it). P-sweep points can double n from existing data. |

Where the review overstates (usable in the rebuttal letter):

- The "mallocがあるのでWCETは数学的に無限" paraphrase is stronger than the paper's actual wording
  ("forfeits the premise of a finite WCET under fragmentation", `06-threats.tex:78-80`); the
  paper's framing is already close to the reviewer's requested "structural hazard" phrasing.
- The line-search-trial divergence concern (#3, #4) is empirically impossible on this engine:
  the pass counter equals N_iter+1 exactly on every real and synthetic frame measured. Cite the
  invariant check; still adopt N_pass in the model for clarity.

## Phase A — prose/logic fixes (no new experiments)

Ordering inside A: **A1 and A2 first** (data integrity — anything a referee can check against our
own tables must be fixed before any other claim is touched), then A3–A6.

### A1 (#10) Real-data honesty — top priority — **DONE (2026-07-12, commit 6a337bb)**

Done as planned, plus: `gen_tables.py` now **hard-fails** if a divergence ever appears off-map,
so the "all 28 divergences are on-map" prose is regenerated-or-broken, never stale; the new
numbers are emitted as generated macros (`\realOnMapMatchPct`, `\realOnMapDivPct`,
`\realDivPctAll`, `\realOffMap*`, `\realOnMapSeqMax`) — the A2 discipline applied to every
touched line. Also updated: `03-methodology.tex` §C and `06-threats.tex` §B (not just §C).
Acceptance verified: no hand-typed `0.12` or unsoftened "validates the contracts" remains in
`sections/ main.tex`; regeneration changes only the realdata outputs; paper builds clean.

- Report the on-map denominator: equal work is 473/501 = **94.4% of on-map frames** (28
  divergences, all on-map), alongside 22,388/22,416 = 99.88% overall. Never present 0.12%
  without the 5.6% on-map figure next to it.
- Explain the off-map cause in the text: the frozen degraded-prior guess track leaves the
  benchmark's cropped map (the comment at `paper/scripts/gen_tables.py:283` is the current only
  record); state the on-map/off-map criterion (sum_neighbors > 0) explicitly.
- Characterize off-map frames (iteration p50 = 0, ~2 ms) so the reader sees they are near-no-ops,
  and recompute/report every distribution row's population clearly (the table footnote already
  splits populations; the prose must too).
- Soften the claim: "validates the contracts and margins" → "one-drive evidence consistent with
  the contracts"; propagate to abstract and intro contribution 4.
- Files: `sections/05-evaluation.tex` §G, `sections/06-threats.tex` §C, `main.tex` abstract,
  `sections/01-introduction.tex`, `tables/realdata.tex` footnote via `gen_tables.py`.
- Acceptance: the words "on-map" and both percentages appear wherever the residual is claimed;
  no reader can derive the 5.6% before we state it.

### A2 (#7, #8) Single-source every number — **DONE (2026-07-12)**

Done as planned, with these specifics: prose macros split into `tails_macros.tex` (timing/
counter/alloc-derived), `gumbel_macros.tex`, `env_macros.tex` (measurement environment from
`wcet.json` `env`+`meta`; §V-A Setup is now macro-driven), and `oneoff_macros.tex` (an
`ONEOFF` dict in `gen_tables.py` holds the side measurements not in `data/` — search-log
gen-0 kd, subnormal shell A/B, exp microbench, malloc-pair ns, kd-iterative speedup — each
with a provenance comment; C1 re-measures/archives them). Rounded qualitative prose claims
("under 10 ms/over 600 ms", "grazes the 100 ms budget", "same per-point constant", the
search-log kd baseline) are now **asserted at generation time** (SystemExit guards,
negative-tested). Timing tables carry a generated "Run: captured …" provenance note;
commit/fixture hashes deferred to C4 (absent from the JSONs — not fabricated). Extra stale
finds fixed: subnormal p50 ratio was 7.3× (actual 7.4×), per-point costs 1.9/0.26 µs (actual
1.8/0.24), allocator share ~8% (actual ~7%), and the regression caption said **n=6 while the
fit uses all 8 fixtures** — review #11's n=6 premise was itself a stale caption; note this in
the rebuttal. The psweep caption now labels the regenerated-geometry distinction. §V-H prose
rewritten to the true β range (0.04–15.8 ms) and +28%/+32% extrapolation, explicitly
low-confidence (full demotion still A6).

- Extend `scripts/gen_tables.py` to emit prose macros the way `psweep_macros.tex` /
  `legal_macros.tex` already work: `\searchZeroMaxCpp`, `\searchZeroMaxRust`, `\gumbelBetaMax`,
  `\gumbelExceedPctCpp`, `\gumbelExceedPctRust`, real-data on-map counts, etc.
- Replace the hand-typed "876 ms → 608 ms" (`05-evaluation.tex:30`), "β ≤ 1.3 ms" and "a few
  percent above the measured maximum" (`05-evaluation.tex:174-177`) with macros. Grep the
  sections for any remaining hard-coded measurement number and macro-ize it.
- Label the psweep-vs-tails discrepancy: Table `psweep` P=2000 (891.2/608.6) is a *regenerated*
  union-worst geometry, not the frozen `search-00` (937.4/656.0) — say so in both captions.
- Add provenance to every table caption: run ID, git commit, fixture hash, measurement date,
  CPU/governor state, sample count (the reviewer's #8 list). Emit from a single manifest block
  in the JSON `meta`.
- Acceptance: `grep -nE '[0-9]+\.[0-9]+' sections/*.tex` finds no timing/β/quantile value that
  is not a macro or clearly a config constant; the `% DATA-CHECKED` comments are replaced by
  generation, not assertion.

### A3 (#1) Reframe the deployment tier around K ≤ 27 — **DONE (2026-07-12)**

Done as planned: §IV-D now states the tier ceiling as the per-tile 27 with the ≤8 explicitly
labeled the voxel-center heuristic (refuted by the real-map K=9, inside 27); *legal-worst* is
"the hardest such input we constructed … the tier's witness — a constructed lower bound — while
the tier's provable ceiling remains K ≤ 27"; §V-F scopes the 4.6×/5.6× as a fixture-to-fixture
measurement with the parametric 64/27 ≈ 2.4× stated as the only guaranteed kernel-term
tightening; §VI-D notes the 27 ceiling has no constructed witness; intro contribution 4 says
"a measured 4.6×, provably ≥2.4× on the kernel term". Boundary-validation point folded into
§VI-D via the preconditions table (see A5).

- The provable per-tile ceiling is **K ≤ 27** (already derived in `04-implementation.tex` §"
  Sufficiency of the neighbor cap"); under disjoint tiles it is also the global ceiling. State
  it as *the* deployment-tier bound.
- Demote *legal-worst* from "deployment geometric ceiling" to **constructed witness / stress
  fixture (a lower bound on the tier's worst case)**; the K = 8 construction is the
  voxel-center heuristic, and the real-map K = 9 observation is presented as refuting that
  heuristic while sitting comfortably inside 27 — one consistent story in §IV-D, §V-F(two-tier),
  §V-G(real data), §VI.
- Re-present 4.6×/5.6× as the **measured gap between the engine-tier and deployment-tier
  fixtures**, explicitly *not* a proven bound-tightening factor; if a bound-tightening number is
  wanted, derive the parametric one from K ≤ 27 (Σnbr ceiling 27·P·N_pass vs 64·P·N_pass ⇒
  provable ≥ 2.37× on the kernel term) and label the rest empirical.
- Add the reviewer's boundary-validation point to §VI (Contract preconditions): the tier bound
  becomes a guarantee only when tile disjointness / voxel-radius coupling / P / leaf count /
  capacity are *checked at the boundary with defined violation behavior* — fold into the A5
  preconditions table and mark runtime-checked vs assumed rows honestly.
- Acceptance: the phrase "geometric ceiling" is attached only to 27; *legal-worst* is nowhere
  called a bound; §IV/§V/§VI tell the same K story.

### A4 (#2) Domain-scope the cross-language transfer — **DONE (2026-07-12)**

Done as planned: §III-C defines the bounded-neighbor domain D (every radius query ≤ 64
in-range leaves) inline, scopes every cross-language worst-case claim to D, and promotes the
equal-work assertion to D's runtime membership check (truncation breaks equal work); §IV-B
says inputs beyond 64 "leave the comparison domain D" and reports the C++ unbounded growth as
a structural hazard "not something this analysis bounds"; "untrusted-input" renamed to
"engine-API worst case (unvalidated inputs)" in abstract/intro/§VI-D; abstract transfer
sentence now carries "over the bounded-neighbor input domain (a runtime-checked condition) …
within that domain".

- Define the comparison domain **D = { inputs whose every radius query returns ≤ 64 in-range
  leaves }** (equivalently: tile multiplicity ≤ 2 over crowded corners) in §III-C, and scope
  every transfer/worst claim to D: "worst input **within D**", "transfers verbatim **within D**".
- The equal-work assertion already doubles as the runtime membership check for D (truncation
  detector, `04-implementation.tex`); promote that from an aside to the definition of D's
  enforcement.
- Report C++ behavior outside D (cost growing with tile multiplicity, allocation hazard) as a
  **hazard finding about the uncapped implementation**, not as a bounded quantity; rename the
  "untrusted-input tier" to "engine-API tier (bounded-neighbor domain)" or similar so the name
  no longer promises unrestricted inputs.
- Files: abstract, `01-introduction.tex` contribution 2, `03-methodology.tex` §C,
  `04-implementation.tex`, `06-threats.tex`.
- Acceptance: no sentence claims a C++ worst case over inputs outside D; the abstract's transfer
  sentence carries the domain qualifier.

### A5 (#4) Rewrite the work model with N_pass — **DONE (2026-07-12)**

Done as planned: Eq (1) now multiplies by N_pass with N_pass = N_iter + 1 and a derivative-pass
definition; the line-search accounting is stated **and source-verified** — the shipped
`computeStepLengthMT` performs exactly one unconditional derivative pass per Newton step
(`multigrid_ndt_omp_impl.hpp:972`), the More–Thuente refinement (≤10 extra passes/iter) is
gated behind `use_line_search`, disabled upstream (FIXME at `:975-982`) and in the port's
default path — so the off-by-one is structural, machine-checked, and observed exactly on all
frames. New hand-maintained `tables/preconditions.tex` (limit / enforced by / on violation,
with assumed rows marked) placed in §VI-D, referenced from §II; kd term's parametric nature on
N_leaves is a table row.

- Eq (1) (`02-problem.tex:31`): replace the N_iter multiplier with **N_pass**, define
  N_pass = N_iter + 1 (initial derivative pass + one per Newton step), and state the line-search
  accounting: the More–Thuente-style step selection in this engine performs **no additional
  derivative passes** — enforced by the property test `passes ≤ N_iter+1` and observed exactly
  (`derivative_passes = iteration_num + 1` on all 22,416 real frames and every fixture).
  Before writing, re-verify in the C++ source that `computeStepLengthMT` cannot re-enter
  `computeDerivatives` in the shipped configuration, and cite where the trial loop is bounded.
- Make the kd term's parametric nature explicit where it is used: Σkd ≤ P · N_pass · N_leaves is
  a bound *given* a leaf-count cap; say who caps N_leaves (map loader / int32 guard — see
  `plan/ndt_wcet.md` operational envelope) or mark it assumed.
- Add the reviewer's **preconditions table** (limit / enforced by / on violation) covering P,
  N_iter, line-search trials, K, N_leaves, buffer capacity — place in §II or §VI; mark each row
  as runtime-checked, build-enforced, or assumed-contract (ties into A3's boundary point).
- Acceptance: the saturation identity P·64·(N_iter+1) and Eq (1) use the same variable; the
  preconditions table exists and every row's enforcer is named.

### A6 (#5, #7) Epistemic tiering, softened claims, pWCET demotion — **DONE (2026-07-12)**

Done as planned: title is now "Toward WCET Analysis of an Industrial NDT Scan Matcher:
Deterministic Cost Search and Cross-Language Validation"; abstract opens with the align-kernel
scope note, the "bit-exact on the tested domain" qualification, and the reviewer's disclaimer
sentence (parametric work bound + empirical unit cost, no certified hard time bound); §VI-E
defines the four evidence tiers and explicitly claims the formally-proven tier for *nothing*;
"proven/provably" purged or downgraded everywhere (abstract, intro contribution 4, §V-C alloc,
§VII, §VIII); zero-allocation now "under a declared capacity contract, counting-allocator-
verified" (incl. the generated alloc-table note); pWCET removed from the abstract and demoted
to "exploratory EVT tail fit for cross-engine comparison" in contribution 1.

- Replace flat "proven" with the four-tier vocabulary everywhere: **enforced by construction**
  (loop guards, hard cap, fixed arrays) / **statically checked** (panic-free lints, no-recursion)
  / **tested** (property tests, counting allocator, differential suite) / **formally proven**
  (reserved; currently nothing). `06-threats.tex` §E is the anchor; abstract and intro follow.
- Zero-allocation claim → "zero allocations **under the declared capacity contract** (verified by
  a counting allocator including the first frame)"; the capacity caveat already in
  `06-threats.tex:56-57` gets referenced from the abstract.
- Soften the allocator-hazard wording toward the reviewer's "structural hazard that resists
  bounding under the current allocator/system model" (small edit; current text is close).
- Title: adopt the reviewer's direction — e.g. "Toward WCET Analysis of an Industrial NDT Scan
  Matcher: Counter-Guided Worst-Input Search and Cross-Language Validation" — and add the
  reviewer's suggested abstract disclaimer sentence (parametric work bound + empirical unit
  cost; no certified hard time bound claimed on the evaluated platform).
- **Demote pWCET**: remove from abstract and contributions; keep §V-H only as "exploratory EVT
  tail fit", with the corrected numbers from A2, until C2 either rebuilds or deletes it.
- "Bit-exact" in title/abstract → qualified per `06-threats.tex` §C ("bit-exact on the tested
  domain") or the reviewer's "work-equivalent on per-input certified traces".
- Also strip the remaining red `\todo{}`s that A/B/C items resolve, and state explicitly that
  the analysis covers the align kernel only (not map build / preprocessing / ROS scheduling) in
  title-adjacent text (reviewer's "次点" list).
- Acceptance: `grep -in "proven\|bit-exact" sections/*.tex main.tex` shows only tiered/qualified
  uses; abstract contains the disclaimer; pWCET absent from abstract/contributions.

## Phase B — new analysis from existing data and tools (no re-measurement)

### B1 (#3) Strengthen the per-input equal-work certificate — **DONE (2026-07-12)**

Both zero-source-change legs done. (a) **Alloc cross-check**: allocs/(pt·pass) computed from
`wcet_alloc.json`/`wcet_rust.json` is 11.003–11.005 on every neighbor-returning fixture — a
0.02% spread across geometries differing 100× in cost, fine enough to expose a single extra
derivative pass (~3%); the one deviation (subnormal, 9.4) is structural (empty queries skip
per-result containers). Guarded in `gen_tables.py` (>0.5% spread fails generation); reported
in §V-C + §III-C. (b) **Pose/score leg**: `bench/ndt_bench_replay.cpp` fixture mode now
records and asserts final pose + transform_probability + NVTL agreement; run on all 8 frozen
fixtures → poses agree to ≤2e-7 m, both scores bit-identical on 7/8 (max delta 6e-8 = one f32
ULP on subnormal); frozen as `data/wcet_cert.json` (deterministic per input, so independent
of the timing run), generation hard-fails if any pose_match goes false. §III-C notes the
real-data replay still certifies the iteration leg only (capture not on disk; re-capture is a
C-phase item). The analysis-fork distinction is documented in §III-C.

The reviewer asks for an instrumented C++ analysis fork. That collides with the project's hard
constraint (upstream C++ byte-identical; see memory `ndt-original-cpp-untouched` and
`03-methodology.tex` §C). Two zero-source-change strengtheners come first:

1. **Assert final pose + score agreement per input** in the replay harness (both engines already
   output them; today only `iteration_num` is asserted at measurement time). Certificate becomes
   (iteration_num equal) ∧ (pose/score within the differential-suite tolerance) per frame.
2. **Use the LD_PRELOAD allocation counts as an independent C++-side work counter**: the
   interposer (already built, `03-methodology.tex` §D) yields allocs ≈ 11 · P · N_pass plus
   per-radius-search terms (682,248/(31·2000) = 11.0), so C++'s P·N_pass and query count are
   cross-checkable against the Rust counters with the production binary untouched. Report the
   per-fixture and real-data cross-check.

Then re-word the claim to the reviewer's "work-equivalent on per-input certified traces". If
referees still insist on trace hashes (Σnbr, Σkd, neighbor-ID hashes from the C++ side), the
documented fallback is a clearly-labeled **analysis-only instrumented C++ build** — the upstream
constraint governs what we ship/PR, not what a measurement harness may compile locally; the paper
should state this distinction (review #3's "製品バイナリ vs 解析専用fork" point) even if we don't
build it.

- Acceptance: replay harness asserts pose/score; alloc-derived C++ counters appear in the paper
  as the second certification leg; methodology §C rewritten around the two-leg certificate.

### B2 (#11) Regression strengthening — **DONE (2026-07-12)**

Pooled design (8 fixtures + 6 P-sweep points, n=14/engine), seeded 2000-resample bootstrap
CIs in Table IV, LOO prediction error (median 4%/7%, worst 58%/91% on *cache-hostile* — the
per-point-overhead fixture the two-term model cannot see, corroborating §V-B), and the
honest headline: **regressor correlation 0.99** — the reviewer's collinearity suspicion
confirmed and reported; coefficients share variance, the combined prediction is what is
identified. The negative Rust intercept's CI covers zero. The C++/Rust kernel-cost CI
disjointness (which carries the 2.1× claim) is asserted at generation time.

- Pool the six P-sweep points into the unit-cost regression (n: 6 → 12 per engine; counters are
  certified invariant per point, `tables/psweep.tex`).
- Add bootstrap confidence intervals for a, b, c; leave-one-fixture-out prediction error;
  a collinearity check (Σnbr vs Σkd correlation across fixtures); report all in the table or an
  appendix. All computable in `scripts/gen_tables.py` (stdlib-only — keep it that way).
- Re-word the attribution ("pcl/FLANN machinery") as arithmetic-plausible hypothesis (already
  done in §V-C/D; keep) and note hardware-counter attribution as C1 follow-up.
- Acceptance: regression table shows n=12, CIs, and LOO error; negative intercept either gone or
  explained with its CI covering zero.

### B3 (#1) K-maximizing legal witness — **DONE (2026-07-12, documented negative)**

`wcet_search_legal.rs` gained a `WCET_SEARCH_FITNESS=maxk` mode (fitness = per-point max K,
then iter, Σnbr; freezes `legal_k.ndtfix` only if K ≥ 9). Three seeds (25–40 gens) through
the unchanged legality verifier all **plateau at K = 6**: the rough-surface family scatters
centroids and cannot crowd 7+ into one search ball. The corner-lattice construction (K = 8)
and the real map (K = 9) remain the strongest known legal witnesses. Frozen as
`data/legal_k_search.json`; reported in §VI-D as evidence (not proof) that legal K
concentrates far below the 27 ceiling.

- Re-run the existing production-parameterized legal search (the legality-verifier machinery
  that produced *legal-osc*, `04-implementation.tex` §D) with fitness = max per-point K (then
  lexicographic on cost) to find a legal K ≥ 9 witness, tightening the empirical gap between the
  K = 8 construction and the K ≤ 27 ceiling.
- Freeze it as *legal-k* (or fold into a rebuilt *legal-worst*) and measure it in the same
  harness; feeds A3's reframed tier narrative.
- Acceptance: the deployment tier has a frozen witness with K ≥ 9, or a documented negative
  search result strengthening the empirical case that legal K stays far below 27.

### B4 (#9) Pareto archive + cheap ablations — deferred (run with C1)

Assessed 2026-07-12: needs a search-driver restructure (non-dominated archive) plus *timing*
of every frontier candidate — timing that would come from the deprecated powersave setup and
be re-measured in C1 anyway. Decision: implement the Pareto archive + hill-climb-vs-random /
multi-seed ablations together with the C1 campaign so the frontier candidates are measured
once, under the final protocol.

- Modify the search driver to archive the counter-space **Pareto frontier** (N_iter, Σnbr, Σkd)
  instead of only the lexicographic best; measure every frontier candidate on the host; report
  whether any non-lexicographic candidate beats *search-00* in wall time.
- Cheap ablations from existing/new search logs: hill-climb vs random-search budget-matched;
  single vs multiple seeds; counter fitness vs wall-clock fitness (one run suffices to show
  noise); evaluations-to-saturation. Present as a small table.
- Re-word "worst-input search" claims to "counter-worst" / scoped to the generator family
  (§III-B, §VI-B already hedge; make the naming consistent).
- Acceptance: paper states whether the Pareto frontier changed the answer; at least the
  hill-climb-vs-random ablation is reported.

### B5 (#10) Real-data scenario breakdown — **DONE (2026-07-12)**

From `realdata.json`: the 501 on-map frames form 15 contiguous segments (route repeatedly
grazes the crop edge); all 28 divergences cluster in 3 segments yet look like ordinary frames
(K̄ near the on-map median, iterations 9–30, only 7 at the cap) and none is the worst frame
(divergent C++ max 87.5 ms vs 99.8 overall) — the signature of the knife-edge ±1 mechanism,
not a blind regime. Macros + a §V-G paragraph; per-scenario (nominal-prior) data remains a
C-phase capture item.

- From `data/realdata.json`: on-map segment structure (the 501 frames span seq 0–539,
  non-contiguous — report segments), per-population stats (on-map vs off-map), where the 28
  divergences sit within on-map segments, iteration/K/timing distributions per scenario
  (initialization / tracking / off-map).
- Feeds A1's prose; also answer the reviewer's "nominal-prior" question honestly: the nominal
  case is future work (multiple routes/priors → C-phase or explicitly future work).
- Acceptance: a per-scenario table or paragraph exists; the 28 divergences are located.

## Phase C — re-measurement (required for resubmission)

These are the paper's own red `\todo{}`s; the review correctly says they are prerequisites, not
future work. Protocol details live in `plan/ndt_wcet.md` (Layer 3) and `plan/ndt_bench.md`
(capture-once/replay-everywhere); this phase just pins what the paper needs.

### C1 (#6) Host measurement redo

- performance governor, isolated core (`isolcpus`/`cset`), cold-cache series alongside warm,
  interference co-runner series, ≥ 3 independent runs on different days, C++/Rust interleaved
  and order-randomized.
- Publish the full build/run manifest: compiler versions and *all* flags (C++ `-O2 …` vs Rust
  release profile: opt-level, LTO, codegen-units, target-cpu), FMA/fast-math status, OpenMP
  runtime presence even at num_threads=1, link mode, allocator, CPU frequency/thermal state,
  SMT/IRQ/NUMA config. Answer #6's "this Rust implementation vs this C++ baseline" framing in
  §V-A prose.
- Acceptance: no measurement claim in the paper rests on the powersave/container data; TODOs
  gone; manifest table present.

### C2 (#7) EVT redo — or delete (decision gate)

- If kept: ≥ 1,000–10,000 samples per fixture across multiple runs/days; POT/GPD (and GEV for
  comparison) with MLE; shape-parameter estimates with CIs; independence/stationarity
  diagnostics; block/threshold sensitivity; per-block → per-align probability conversion;
  extrapolation distance stated. Only then may pWCET reappear beyond "exploratory".
- If not affordable: delete §V-H and Table `gumbel`, keep max/percentile tails only. The paper
  is publishable without pWCET; it is not publishable with the current n=10 fit as a claim.
- Acceptance: either the full protocol above or no pWCET table; A6's demotion holds meanwhile.

### C3 (#6) AArch64 target evidence — **counter leg DONE on hardware (2026-07-12)**

**Raspberry Pi 4 result integrated into the paper.** `data/raspi4.txt` (frozen serial log,
Cortex-A72, bare-metal no_std kernel) shows **7/8 exact counter equality**; *search-01*'s
divergence (+2 Σnbr / −1 Σkd) reproduces **bit-identically to QEMU-TCG**, i.e. it is a
property of the generated AArch64 code, not the emulator (no fmadd in the binary, IEEE FPCR,
deterministic). Paper updated: new §V-I "On-target counter transfer (AArch64)" +
Table `raspi4` (generated by the new `raspi4()` emitter with regenerate-or-break guards:
host comparison recomputed from `wcet_rust.json`, mismatch set pinned to exactly search-01
at +2/−1); §III-E rewritten from "future work" to the executed protocol with the
"ISA-independent up to a certificate-flagged residual" qualification; §VI-C measured
statement; abstract transfer sentence extended; conclusion future-work updated. Single-shot
align times reported as informational (n=1, no warmup — not the C1 protocol).

**search-01 divergence ROOT-CAUSED (2026-07-12, later): NOT an ISA effect — a stale
baseline.** Host probe at the baseline's own toolchain (rustc 1.96) reproduced the *target*
values (2,321,941/10,787,955) at engine HEAD; commit-bisect via git worktrees pinned the flip
to **`7caf44d7`** (pcl f32 transform-association mirror, one of the two port-fidelity fixes,
landed 07-11 morning) — the frozen `wcet_rust.json` was captured 07-10 21:27, *before* it.
The fix shifts the knife-edge fixture by 2 evaluations in 2.3 M; the other 7 fixtures are
insensitive (verified byte-identical). Remediation: `wcet_rust.json` regenerated at engine
HEAD (a58673ae) with a provenance `meta` block; only search_01 changes. Host == QEMU == Pi 4
**exactly on all 8** — `data/raspi4.txt` was already an 8/8-exact hardware run against the
correct baseline. `raspi4()` guard redesigned (recomputed mismatch must be empty; the
historical on-device 7/8 verdict is pinned and explained in the table note). Paper updated:
§V-I retold as the certificate catching a *version skew* at ppm resolution (counters =
behavioral fingerprint of the engine version ⇒ commit-pinned baselines, feeding C4);
§III-E/§VI-C/abstract now claim exact transfer on all 8. Kernel app expectation table
updated (+ QEMU 8/8 verification). The user then re-captured the Pi 4 log with the updated
app: `data/raspi4.txt` now shows **8/8 OK on-device**, counters bit-identical between the
two hardware runs (the first run's 7/8 log lives in git history at ba7068d and is narrated
as history in §V-I).

Remaining for C3:
- the controlled **timing** protocol on target (repeats, warm/cold, co-runner) — rides C1.

Original scope (for reference):

**Status**: the bare-metal AArch64 kernel platform (`/autoware_workspace/awkernel`, branch
`ndt_rs`) boots on QEMU Raspberry Pi 3 (`make aarch64 BSP=raspi3 RELEASE=1`, `make
qemu-raspi3`): 4 CPUs, BLisp shell responsive. A new async app `applications/ndt` embeds all
8 frozen fixtures (no_std NDTFIX01 byte parser; the engine's fixture module is std-only),
runs one counted align each (engine built `--no-default-features --features wcet-count`,
single-core, no `mt`), and asserts the counters against `paper/data/wcet_rust.json`. Build:
`make aarch64 BSP=raspi3 RELEASE=1 FEATURES=ndt` (new Makefile `FEATURES` passthrough).

**Result: 7/8 exact counter equality — and one real finding.** *search-01* diverges
deterministically and microscopically on the target: Σnbr 2,321,941 vs host 2,321,939 (+2),
Σkd 10,787,955 vs 10,787,956 (−1); iterations/passes/points identical; bit-identical across
two QEMU runs. Ruled out: FMA contraction (zero fmadd/fmsub in the kernel binary), FP-context
corruption (deterministic), flush-to-zero (FPCR at IEEE default; *subnormal* passes exactly).
Remaining candidates: a QEMU TCG softfloat subtlety vs a genuine codegen difference — **the
Raspberry Pi 4 hardware run discriminates**. Do not touch the §III-E ISA-independence claim
until the hardware result is in; if the divergence survives on hardware, §III-E needs a
measured caveat (per-pass counter dump to find the first divergent pass, then a targeted
fix or a documented domain restriction).

Remaining for C3 proper:
- Raspberry Pi 4 hardware run (same `FEATURES=ndt` image path, BSP=raspi4): counter equality
  first, then the timing protocol (cycle counter / `uptime_nano` per align, C1-grade
  repeats) for the target-platform unit-cost bound of §VI-E.
- Root-cause the search-01 delta (per-pass counters on both sides; qemu-user cross-check if
  tools become available).
- Acceptance: cross-ISA claims match the evidence actually collected.

### C4 (#8) One-manifest regeneration

- All C-phase data lands in `paper/data/*.json` with a `meta.manifest` block (run ID, commits,
  fixture hashes, binary hashes, date, CPU config, sample count); `scripts/gen_tables.py`
  regenerates **every** table, figure, and prose macro from it (A2 made the prose macro-driven,
  so this is push-button). Pin exact autoware_core/port commits (`04-implementation.tex` TODO).
- Acceptance: `python3 scripts/gen_tables.py && make -C paper` reproduces the submitted PDF's
  numbers exactly from the JSONs.

## Milestones / ordering

| Milestone | Items | Gate |
|---|---|---|
| M1 — data integrity | ~~A1~~ (done, 6a337bb), ~~A2~~ (done, 2026-07-12) | **COMPLETE.** Nothing a referee can cross-check against our own tables is wrong. |
| M2 — claims consistent | ~~A3, A4, A5, A6~~ (done, 2026-07-12) | **COMPLETE.** The paper no longer contradicts itself; every claim scoped to its evidence. Rebuttal letter can be drafted. |
| M3 — existing-data strengthening | ~~B1, B2, B5, B3~~ (done, 2026-07-12); B4 → C1 | **COMPLETE** (B4 deliberately folded into the C1 campaign). |
| M4 — measurement redo | C1, then C2 decision, C3, C4 | Resubmission-ready experiments. |
| M5 — resubmission package | re-run audit table against final PDF; rebuttal letter from the audit table (including the two push-back points) | Submit. |

A before B before C. B3/B4 can run concurrently with C1 (different machines/queues). The review's
"次点" items not explicitly scheduled above (artifact publication of generators/seeds/fixtures,
multiple routes/nominal-prior drive) are strengthening add-ons: artifact publication rides C4;
extra drives are declared future work unless time permits.

## Acceptance checklist (review point → roadmap item)

- #1 → A3 ✓ + B3 ✓ - #2 → A4 ✓ - #3 → B1 ✓ (+ A6 ✓ wording)
- #4 → A5 ✓ - #5 → A6 ✓ - #6 → C1 + C3 (✓ counters on hardware; timing rides C1)
- #7 → A2 ✓ + A6 ✓ + C2 - #8 → A2 ✓ + C4 - #9 → B4 (rides C1)
- #10 → A1 ✓ + B5 ✓ - #11 → B2 ✓
- Review's title/abstract suggestions → A6 ✓.

## Status log

- 2026-07-11: roadmap written (commit c42b6c8, together with `paper/review.md`).
- 2026-07-12: **A1 done** (commit 6a337bb) — on-map denominator (473/501 = 94.4% equal work,
  28 divergences all on-map = 5.6%) reported everywhere the residual is claimed; off-map
  near-no-op characterization + prefix-window cause in §V-G; "validates" softened to one-drive
  evidence; new `\realOnMap*`/`\realOffMap*`/`\realDiv*` macros generated by `gen_tables.py`
  with a hard-fail guard on the "all divergences on-map" invariant. Next: A2.
- 2026-07-12: **A2 done — M1 complete** — every measurement number in the prose is now a
  generated macro (tails/gumbel/env/oneoff macro files), qualitative rounded claims are
  asserted at generation time, timing tables carry generated provenance notes, and the stale
  spots (876/608, β ≤ 1.3, "a few percent", 7.3×, regression n=6-vs-8 caption) are fixed.
  Review #11 note for the rebuttal: the regression n was mislabeled — the fit already uses
  all 8 fixtures. Next: M2 (A3–A6).
- 2026-07-12: **M2 done (A3+A4+A5+A6)** — deployment tier reframed around the provable K ≤ 27
  with legal-worst demoted to constructed witness and 4.6× scoped as measured (provable
  kernel-term tightening 64/27 ≈ 2.4×); bounded-neighbor domain D defined and every
  cross-language claim scoped to it ("untrusted-input" renamed); Eq (1) rewritten with
  N_pass = N_iter+1 (line-search accounting source-verified: `use_line_search` disabled
  upstream, one unconditional derivative pass per step) plus a hand-maintained preconditions
  table (`tables/preconditions.tex`) in §VI-D; title → "Toward WCET Analysis…", abstract
  gains the scope note + disclaimer, four evidence tiers defined in §VI-E (formally-proven
  claimed for nothing), pWCET out of the abstract. Rebuttal letter is now unblocked; next:
  M3 (B1, B2, B5, then B3, B4).
- 2026-07-12: **M3 done (B1+B2+B5+B3; B4 → C1)** — equal-work certificate now three-legged
  (iteration + pose/score on fixtures [≤2e-7 m, scores bit-identical 7/8, `wcet_cert.json`]
  + the LD_PRELOAD alloc cross-check [11.003–11.005 allocs/(pt·pass), 0.02% spread]);
  regression pooled to n=14 with bootstrap CIs / LOO / the confirmed 0.99 collinearity;
  real-data residual located (15 segments, divergences in 3, none the worst frame); max-K
  legal search: documented negative (3 seeds plateau at K=6; lattice 8 / real 9 / ceiling 27).
  Harness changes live in the autoware_core clone (`bench/ndt_bench_replay.cpp` cert leg,
  `wcet_search_legal.rs` maxk fitness mode) — commit there with sign-off. B4 (Pareto +
  ablations) deliberately rides C1 so frontier candidates are timed once under the final
  protocol. Next: M4 (C1–C4).
- 2026-07-12 (later): **C3 platform prep done** — no_std kernel boots on QEMU raspi3; new
  `applications/ndt` async app runs all 8 frozen fixtures on bare-metal AArch64 with the
  wcet-count engine; **7/8 counters exactly equal the host**; *search-01* shows a
  deterministic +2 Σnbr / −1 Σkd divergence (FMA/FZ/context-corruption ruled out; QEMU-TCG
  vs codegen still open — Pi 4 hardware run discriminates). Kernel-side changes live in the
  kernel repo (app crate + feature wiring + Makefile FEATURES passthrough); commit messages
  there must say "no_std", never the kernel's name.
- 2026-07-12 (later still): **C3 counter leg done on hardware** — Raspberry Pi 4 serial log
  frozen as `data/raspi4.txt`; 7/8 exact, search-01 +2/−1 bit-identical to QEMU ⇒ generated-
  code property. Paper integrated (new §V-I + Table raspi4 via guarded `raspi4()` emitter,
  §III-E executed-protocol rewrite, §VI-C measured qualification, abstract + conclusion).
  This closes reviewer #6's cross-ISA evidence demand, exception honestly included.
  Remaining in M4: C1 (host redo + B4 + target timing), C2 (EVT decision), C4 (manifest),
  search-01 root cause.
- 2026-07-12 (root cause): **search-01 divergence solved — stale baseline, not ISA.**
  Bisect: pre-fix worktree (660c1ea0) reproduces 2,321,939/10,787,956; the flip lands with
  `7caf44d7` (pcl f32 transform-association mirror). Baseline refreshed at engine HEAD
  (only search_01 changes; 7 others byte-identical), raspi4 guard redesigned, paper retold
  (§V-I certificate-catches-version-skew; §III-E/§VI-C/abstract → exact on all 8), kernel
  app expectations updated, QEMU re-verified. `data/raspi4.txt` needed no re-capture — the
  hardware run was already exact against the correct baseline. C3 fully closed except the
  target timing protocol (rides C1).

## Cross-references

- `paper/review.md` — the review being addressed (point numbers #1–#11).
- `paper/scripts/gen_tables.py` — single-source table/macro generator (A2, B2, C4 extend it).
- `paper/data/*.json` — frozen measurement data; audit findings above were verified against
  `realdata.json` (on-map split, divergence locations) and `wcet.json`.
- `plan/ndt_wcet.md` — the measurement/EVT protocol layer (C1/C2 details, operational envelope
  for the N_leaves precondition in A5).
- `plan/ndt_bench.md` — capture-once/replay-everywhere fixture discipline (C-phase replays).
- Memory `ndt-original-cpp-untouched` — the constraint shaping B1's no-fork-first strategy.
