# WCET paper — NDT scan matcher, C++ vs bit-exact Rust port

LaTeX source for the WCET-analysis paper (IEEEtran conference format; switch the class if the
target venue requires LIPIcs — the ECRTS WCET Workshop is the primary candidate).

## Build

```sh
make            # gen_tables.py + latexmk -> main.pdf
make tables     # regenerate tables/*.tex from data/*.json only
make clean      # drop latexmk intermediates
```

## Layout

- `main.tex` — class, macros (`\sumnbr`, `\kdnodes`, `\maxnn`, `\todo{}`), abstract, `\input`s.
- `sections/01…08` — one file per section; `\todo{...}` marks every gap (red in the PDF).
- `data/*.json` — **frozen measurement snapshot** (copied from a `bench/run_wcet.sh` run:
  `wcet.json` timing, `wcet_rust.json` counters, `wcet_alloc.json` allocation pass).
- `scripts/gen_tables.py` — stdlib-only; renders `tables/*.tex` from `data/`. Tables are
  committed build products — never hand-edit them.
- `tables/*.tex` — generated (counters, tails, alloc, regression, gumbel).

## Data pipeline (reproducing / refreshing the numbers)

1. In the dev container, from the workspace root:
   `TASKSET="taskset -c 2" OUT_DIR=/tmp/wcet_out bash src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench/run_wcet.sh`
2. `cp /tmp/wcet_out/{wcet.json,wcet_rust.json,wcet_alloc.json} paper/data/`
3. `make tables && make`

The current snapshot is the 2026-07-10 container run (Ryzen 5900HX, **powersave governor** —
flagged as a TODO in Sec. Evaluation/Threats; redo with performance governor + isolated core
before submission).

## Open TODOs (mirrors `\todo{}` marks)

- Re-measure host with performance governor / isolated core / cold-cache / co-runner.
- EVT strengthening: 1000+ samples, PoT/MLE, confidence intervals, repeated runs.
- AArch64 bare-metal target: counter-equality verification + target tail table (M5 hardware half).
- Related-work verification (bib entries are drafts — check venues/pages) + missing citations
  (ndt_omp, Rust-RT, kernel target).
- Author list / affiliations / acknowledgments.
