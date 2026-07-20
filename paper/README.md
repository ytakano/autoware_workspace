# Timing-evidence paper — NDT scan matcher, C++ vs Rust port

LaTeX source for the WCET-analysis paper (IEEEtran conference format; switch the class if the
target venue requires LIPIcs — the ECRTS WCET Workshop is the primary candidate).

## Build

```sh
make            # regenerate all tables, including EVT diagnostics, then build main.pdf
make tables     # regenerate tables/*.tex from data/*.json only
make clean      # drop latexmk intermediates
```

## Layout

- `main.tex` — class, macros (`\sumnbr`, `\kdnodes`, `\maxnn`, `\todo{}`), abstract, `\input`s.
- `sections/01…09` — one file per section and the appendix; `\todo{...}` marks open gaps.
- `data/*.json` — frozen timing, counter, allocation, trace, replay, and target snapshots.
  The unified timing files are pooled by `scripts/integrate_campaign.py`.
- `scripts/gen_tables.py` and `scripts/evt.py` — stdlib-only; render `tables/*.tex` from
  `data/`. Tables are committed build products — never hand-edit them.
- `tables/*.tex` — generated counters, timing, allocation, regression, and EVT diagnostics.

## Data pipeline (reproducing / refreshing the numbers)

1. Run the unified campaign for three distinct boots using
   `bench/campaign_config_unified.json`.
2. Validate and pool the sessions with
   `python3 paper/scripts/integrate_campaign.py --check-only`, then run the same command
   without `--check-only` to refresh `paper/data/wcet*.json`.
3. Run `make`.

The current host snapshot is the 2026-07-18/2026-07-19 three-boot campaign on the Ryzen
5900HX with the performance governor and isolated benchmark core. Timing integration rejects
trace-enabled binaries.

## Open TODOs (mirrors `\todo{}` marks)

- Related work: written and cited (17 entries, venues verified 2026-07-10); re-check page
  numbers for wilhelm2008wcet / cazorla2019mbpta / edgar2001gumbel at camera-ready; add the
  no_std kernel target citation once public.
- Author list / affiliations / acknowledgments.
