# Timing-evidence paper — NDT scan matcher, C++ vs Rust port

LaTeX source for the WCET-analysis paper (IEEEtran conference format; switch the class if the
target venue requires LIPIcs — the ECRTS WCET Workshop is the primary candidate).

**Reproducing the results:** see [`REPRODUCE.md`](REPRODUCE.md) for the tiered guide
(T0 build the PDF → T1 regenerate tables → T2 re-run the WCET campaign, plus pointers to the
hardware-bound stack-replay and Raspberry Pi 4 experiments). The `scripts/reproduce.sh` driver
automates the hardware-independent tiers (T0/T1).

## Build

```sh
make            # regenerate all tables, including EVT diagnostics, then build main.pdf
make tables     # regenerate tables/*.tex from data/*.json only
make clean      # drop latexmk intermediates
```

## Layout

- `main.tex` — class, notation macros, abstract, and section inputs.
- `sections/01…09` — one file per section and the appendix.
- `data/*.json` — frozen timing, counter, allocation, trace, replay, and target snapshots.
  The unified timing files are pooled by `scripts/integrate_campaign.py`.
- `data/raspi4_timing.txt` and `data/raspi4_timing_meta.json` — the complete AArch64
  serial log and its source-image, commit, and content-hash provenance.
- `scripts/gen_tables.py` and `scripts/evt.py` — stdlib-only; render `tables/*.tex` from
  `data/`. Tables are committed build products — never hand-edit them.
- `tables/*.tex` — generated counters, timing, allocation, regression, and EVT diagnostics.

## Data pipeline (reproducing / refreshing the numbers)

1. Run the bounded unified campaign for three distinct boots using
   `plan/campaign_config_unified_bounded.json`. Run the capacity-parameterized sweep with
   `bench/campaign_config_psweep.json`.
2. Validate and pool the sessions with
   `python3 paper/scripts/integrate_campaign.py --check-only`, then run the same command
   without `--check-only` to refresh the unified `paper/data/wcet*.json` files. Pool the sweep with:

   ```sh
   python3 paper/scripts/integrate_campaign.py \
     --runs-dir src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench/campaign_runs/psweep_3x100_bounded \
     --config src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench/campaign_config_psweep.json \
     --warm-output-name wcet_psweep.json --warm-only
   ```
3. Run `make`.

The current host snapshot is the 2026-07-20/2026-07-21 three-boot campaign on the Ryzen
5900HX with the performance governor and isolated benchmark core. Timing integration rejects
trace-enabled binaries, reused boot IDs, campaign-identity drift, and any cell whose environment
sidecar records a measurement problem.
